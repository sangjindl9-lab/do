"""에이전트가 보낸 검사 결과 저장. 실제 수행되지 않은 단계는 not_run으로만 기록된다."""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (CrashLog, Customer, Device, PerformanceMetric, Product, TestJob, TestPlan, TestResult)
from . import analysis
from .notifications import notify

VALID_STEP = {"passed", "failed", "not_run", "skipped"}


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 60 * 2 ** max(0, attempts - 1)))


def retry_or_fail(db: Session, job: TestJob, reason: str, final_status: str = "failed") -> None:
    """실패 작업 재시도(지수 백오프). 최대 횟수 초과 시 오류 결과를 남긴다(성공으로 기록하지 않음)."""
    job.lease_token, job.lease_expires_at, job.error = None, None, reason[:2000]
    if job.attempts < job.max_attempts:
        job.status, job.next_attempt_at, job.progress = "queued", utcnow() + backoff(job.attempts), 0
        return
    job.status, job.finished_at = final_status, utcnow()
    plan = db.get(TestPlan, job.plan_id)
    if not db.scalar(select(TestResult.id).where(TestResult.job_id == job.id)):
        db.add(TestResult(job_id=job.id, plan_id=job.plan_id, device_id=job.device_id,
                          app_version_id=job.app_version_id, customer_id=plan.customer_id, status="error",
                          steps=[], summary={"reason": reason[:500], "final_status": final_status,
                                             "note": "검사가 수행되지 못했습니다."},
                          started_at=job.started_at, finished_at=utcnow(), is_mock=job.is_mock))
    owner = db.get(Customer, plan.customer_id).user_id
    notify(db, owner, "test_error", {"app": plan.app.name, "reason": reason[:200]}, f"/dashboard/orders/{plan.order_id}")


def installed_devices(db: Session, plan: TestPlan) -> int:
    """앱 실행이 확인된(=설치된) 기기 수."""
    db.flush()
    rows = db.execute(select(TestResult.device_id, TestResult.steps).where(TestResult.plan_id == plan.id)).all()
    return len({d for d, steps in rows if any(s.get("key") == "launch" and s.get("status") == "passed" for s in steps or [])})


def update_count(db: Session, plan: TestPlan) -> int:
    """테스트 시작 후 14일 안에 검사 기기에서 확인된 앱 업데이트 횟수(설치 버전이 바뀐 횟수)."""
    rows = db.scalars(select(TestResult.summary).where(TestResult.plan_id == plan.id,
                                                       TestResult.created_at <= plan.start_at + timedelta(days=14))).all()
    versions = {(s or {}).get("installed_version") for s in rows} - {None, ""}
    return max(0, len(versions) - 1)


def start_period_if_ready(db: Session, plan: TestPlan) -> None:
    """12대(상품 기기 수가 더 적으면 그 수) 이상 설치되면 그 시점부터 검사 기간을 계산한다."""
    if plan.period_started:
        return
    # 여러 기기의 결과가 동시에 들어오므로 계획 행을 잠근 뒤 센다(잠금 대기 후에는 먼저 끝난 결과가 보인다).
    db.flush()
    db.execute(select(TestPlan.id).where(TestPlan.id == plan.id).with_for_update(key_share=True))  # FOR NO KEY UPDATE: FK 잠금과 충돌하지 않음
    db.refresh(plan)
    if plan.period_started:
        return
    if installed_devices(db, plan) >= min(12, plan.device_count):
        now = utcnow()
        duration = plan.end_at - plan.start_at
        plan.start_at, plan.end_at, plan.period_started = now, now + duration, True


def ingest(db: Session, job: TestJob, body: dict) -> TestResult:
    existing = db.scalar(select(TestResult).where(TestResult.job_id == job.id))
    if existing:
        return existing  # 멱등: 재전송된 결과
    if job.status not in ("leased", "running"):
        raise HTTPException(409, "결과를 받을 수 없는 작업 상태입니다.")
    status = body.get("status")
    if status not in ("passed", "failed"):
        raise HTTPException(400, "status는 passed 또는 failed여야 합니다.")
    steps = []
    for s in body.get("steps") or []:
        st = s.get("status")
        if st not in VALID_STEP:
            raise HTTPException(400, f"잘못된 단계 상태: {st}")
        steps.append({"key": str(s.get("key", ""))[:60], "name": str(s.get("name", ""))[:160], "status": st,
                      "expected": str(s.get("expected", ""))[:500], "actual": str(s.get("actual", ""))[:500],
                      "duration_ms": int(s.get("duration_ms") or 0), "detail": str(s.get("detail", ""))[:2000]})
    if not steps:
        raise HTTPException(400, "검사 단계 결과가 없습니다.")
    if status == "passed" and any(s["status"] == "failed" for s in steps):
        raise HTTPException(400, "실패한 단계가 있는 결과를 성공으로 기록할 수 없습니다.")
    if status == "passed" and not any(s["status"] == "passed" for s in steps):
        raise HTTPException(400, "수행된 단계가 없는 결과를 성공으로 기록할 수 없습니다.")
    plan = db.get(TestPlan, job.plan_id)
    issues = body.get("issues") or []
    result = TestResult(job_id=job.id, plan_id=plan.id, device_id=job.device_id, app_version_id=job.app_version_id,
                        customer_id=plan.customer_id, status=status, steps=steps, summary=body.get("summary") or {},
                        device_info=body.get("device_info") or {}, started_at=_ts(body.get("started_at")) or job.started_at,
                        finished_at=_ts(body.get("finished_at")) or utcnow(), duration_ms=int(body.get("duration_ms") or 0),
                        crash_count=sum(1 for i in issues if i.get("kind") == "crash"),
                        anr_count=sum(1 for i in issues if i.get("kind") == "anr"), is_mock=job.is_mock)
    db.add(result)
    db.flush()
    for m in body.get("metrics") or []:
        try:
            db.add(PerformanceMetric(result_id=result.id, plan_id=plan.id, device_id=job.device_id,
                                     metric=str(m["metric"])[:40], value=float(m["value"]), unit=str(m.get("unit", ""))[:20]))
        except (KeyError, TypeError, ValueError):
            continue
    use_ai = bool((plan.order.product_snapshot or {}).get("ai_analysis"))
    owner = db.get(Customer, plan.customer_id).user_id
    for issue in issues[:50]:
        kind = issue.get("kind") if issue.get("kind") in ("crash", "anr", "logcat_error") else "logcat_error"
        title, detail = str(issue.get("title", ""))[:300], str(issue.get("detail", ""))[:20000]
        sig = analysis.signature_of(kind, title, detail)
        rule = analysis.analyze_rule(kind, title, detail)
        known = db.scalar(select(CrashLog.id).where(CrashLog.plan_id == plan.id, CrashLog.signature == sig).limit(1))
        ai = analysis.analyze_ai(db, kind, title, detail) if use_ai and not known and kind != "logcat_error" else None
        db.add(CrashLog(result_id=result.id, plan_id=plan.id, device_id=job.device_id, customer_id=plan.customer_id,
                        app_version_id=job.app_version_id, kind=kind, signature=sig, title=title, detail=detail,
                        severity=rule["severity"], category=rule["category"],
                        analysis={"rule": rule, "ai": ai}, analysis_source="ai" if ai and not ai.get("error") else "rule",
                        is_mock=job.is_mock))
        if not known and kind in ("crash", "anr"):
            notify(db, owner, "crash_found", {"app": plan.app.name, "kind": "크래시" if kind == "crash" else "ANR",
                                              "title": title[:120]}, f"/dashboard/orders/{plan.order_id}")
    start_period_if_ready(db, plan)
    job.status, job.finished_at, job.progress = "succeeded", utcnow(), 100
    job.lease_token, job.lease_expires_at, job.error = None, None, ""
    device = db.get(Device, job.device_id)
    device.last_test_at = utcnow()
    return result
