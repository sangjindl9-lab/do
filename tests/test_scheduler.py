"""자동화: 검사 예약·대기열·중복 실행 방지·실패 재시도·타임아웃·서버 재시작 복구·보고서 생성."""
import threading
from datetime import timedelta

from sqlalchemy import func, select

from conftest import Farm
from test_payment import retire_all


def paid_plan(client, customer, db, product="BASIC"):
    from app.models import TestPlan
    app, version = customer.make_app()
    order = customer.order(app, version, product)
    res, _ = customer.pay(order)
    assert res.status_code == 200, res.text
    return db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))


def test_schedule_repeats_and_never_duplicates(client, admin, customer, mock_pg, farm, db):
    from app.db import utcnow
    from app.models import TestJob, TestSchedule
    from app.services import scheduler
    plan = paid_plan(client, customer, db)
    now = utcnow()
    assert scheduler.tick_schedules(db, now) == 5
    assert scheduler.tick_schedules(db, now) == 0
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == plan.id))
    assert sched.run_times == ["17:00"]                                    # 매일 한국시간 오전 2시(UTC 17:00)
    nxt = sched.next_run_at
    assert (nxt.hour, nxt.minute) == (17, 0) and timedelta(0) < nxt - now <= timedelta(hours=24)
    assert scheduler.tick_schedules(db, nxt - timedelta(minutes=1)) == 0
    assert scheduler.tick_schedules(db, nxt + timedelta(minutes=1)) == 5                                  # 반복 검사
    assert db.scalar(select(func.count()).select_from(TestJob).where(TestJob.plan_id == plan.id)) == 10
    # 특정 시간 검사(관리자 설정)
    r = client.patch(f"/api/admin/plans/{plan.id}", headers=admin, json={"run_times": ["03:00", "15:00"], "daily_runs": 2})
    assert r.status_code == 200 and r.json()["run_times"] == ["03:00", "15:00"]
    assert client.patch(f"/api/admin/plans/{plan.id}", headers=admin, json={"run_times": ["25:00"]}).status_code == 400
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_concurrent_claims_never_double_run(client, admin, customer, mock_pg, farm, db):
    """동시에 여러 번 작업을 요청해도 같은 작업·같은 기기가 중복 실행되지 않는다."""
    from app.models import TestJob
    from app.services import scheduler
    plan = paid_plan(client, customer, db)
    scheduler.tick_schedules(db)
    farm.agent.heartbeat()
    claimed, errors = [], []

    def worker():
        try:
            claimed.extend(farm.api.claim(5))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    ids = [j["id"] for j in claimed]
    assert len(ids) == len(set(ids)) == 5
    assert len({j["serial"] for j in claimed}) == 5
    assert farm.api.claim(5) == []
    assert db.scalar(select(func.count()).select_from(TestJob).where(TestJob.plan_id == plan.id, TestJob.status == "leased")) == 5
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_failed_job_retries_with_backoff_then_records_error(client, admin, customer, mock_pg, db):
    from app.db import utcnow
    from app.models import TestJob, TestResult
    from app.services import scheduler
    retire_all(db)
    farm = Farm(client, admin, count=5)
    farm.cycle()
    plan = paid_plan(client, customer, db)
    scheduler.tick_schedules(db)
    bad = farm.provider.serials[0]
    farm.provider.faults[bad] = "adb_error"        # 이 기기는 검사를 수행할 수 없음
    farm.cycle()
    db.expire_all()
    job = db.scalar(select(TestJob).join(TestJob.device).where(TestJob.plan_id == plan.id).filter_by().where(
        TestJob.device.has(serial=bad)))
    assert job.status == "queued" and job.attempts == 1 and "기기 제어 오류" in job.error
    first_delay = job.next_attempt_at - utcnow()
    assert timedelta(seconds=30) < first_delay <= timedelta(seconds=61)       # 지수 백오프 1차: 60초
    assert db.scalar(select(func.count()).select_from(TestResult).where(TestResult.plan_id == plan.id)) == 4
    farm.cycle()
    db.refresh(job)
    assert job.attempts == 1                                                   # 백오프 시간 전에는 재실행되지 않음
    for expected in (2, 3):
        job.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
        farm.cycle()
        db.refresh(job)
        assert job.attempts == expected
    assert job.status == "failed"                                              # 최대 재시도 횟수 초과
    res = db.scalar(select(TestResult).where(TestResult.job_id == job.id))
    assert res.status == "error" and res.steps == [] and "검사가 수행되지 못했습니다" in res.summary["note"]
    events = [n["event"] for n in client.get("/api/notifications", headers=customer.h).json()["items"]]
    assert "test_error" in events
    # 관리자 재시도 → 기기 복구 후 성공
    farm.provider.faults.clear()
    assert client.post(f"/api/admin/jobs/{job.id}/retry", headers=admin).status_code == 200
    farm.cycle()
    db.refresh(job)
    assert job.status == "succeeded"
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)
    farm.retire(db)


def test_timeout_reclaims_lease_and_server_restart_recovers(client, app, admin, customer, mock_pg, farm, db):
    """임대 만료 작업 회수 + 서버 재시작(새 앱 인스턴스) 후에도 일정·작업이 보존된다."""
    from fastapi.testclient import TestClient
    from app.db import utcnow
    from app.models import TestJob, TestSchedule
    from app.services import scheduler
    plan = paid_plan(client, customer, db)
    scheduler.tick_schedules(db)
    farm.agent.heartbeat()
    leased = farm.api.claim(5)                       # 작업을 받아 놓고 에이전트가 죽은 상황
    assert len(leased) == 5
    with TestClient(app) as restarted:               # 서버 재시작(시작 절차 재실행)
        assert restarted.get("/api/health").json()["status"] == "ok"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(TestJob).where(TestJob.plan_id == plan.id, TestJob.status == "leased")) == 5
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == plan.id))
    assert sched.status == "active" and sched.next_run_at is not None
    assert scheduler.tick_leases(db, utcnow() + timedelta(minutes=10)) == 0     # 아직 타임아웃(30분) 전
    assert scheduler.tick_leases(db, utcnow() + timedelta(minutes=31)) == 5     # 만료 작업 회수
    db.expire_all()
    jobs = db.scalars(select(TestJob).where(TestJob.plan_id == plan.id)).all()
    assert all(j.status == "queued" and j.lease_token is None and "타임아웃" in j.error for j in jobs)
    # 만료된 임대로는 결과를 낼 수 없다
    stale = client.post(f"/api/agent/jobs/{leased[0]['id']}/result", headers={"X-Agent-Token": farm.cfg.token},
                        json={"lease_token": leased[0]["lease_token"], "status": "failed", "steps": [{"key": "a", "name": "a", "status": "failed"}]})
    assert stale.status_code == 409
    for j in jobs:                                    # 에이전트 재접속 후 복구
        j.next_attempt_at = utcnow() - timedelta(seconds=1)
    db.commit()
    farm.cycle()
    db.expire_all()
    assert all(j.status == "succeeded" and j.attempts == 2 for j in db.scalars(select(TestJob).where(TestJob.plan_id == plan.id)))
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_agent_spools_results_while_offline_and_syncs(client, admin, customer, mock_pg, farm, db):
    """인터넷 장애 시 결과를 로컬에 보관하고, 연결 복구 후 동기화한다."""
    from gat_agent.api import NetworkError
    from app.models import TestResult
    from app.services import scheduler
    plan = paid_plan(client, customer, db)
    scheduler.tick_schedules(db)
    farm.agent.heartbeat()
    real_result, real_shot = farm.api.result, farm.api.screenshot

    def down(*a, **k):
        raise NetworkError("network down")

    farm.api.result = farm.api.screenshot = down
    farm.agent.claim_and_start()
    assert farm.agent.wait_idle(60)
    assert db.scalar(select(func.count()).select_from(TestResult).where(TestResult.plan_id == plan.id)) == 0
    spooled = farm.agent.spool.items()
    assert sum(1 for n in spooled if n.endswith("-result.json")) == 5 and any(n.endswith("-shot.json") for n in spooled)
    farm.api.result, farm.api.screenshot = real_result, real_shot
    assert farm.agent.flush_spool() == len(spooled)
    assert farm.agent.spool.items() == []
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(TestResult).where(TestResult.plan_id == plan.id)) == 5
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_offline_device_is_replaced(client, admin, customer, mock_pg, db):
    from app.db import utcnow
    from app.models import Device, DeviceAssignment
    from app.services import scheduler
    retire_all(db)
    farm = Farm(client, admin, count=6)
    farm.cycle()
    plan = paid_plan(client, customer, db)
    assigned = db.scalars(select(DeviceAssignment).where(DeviceAssignment.plan_id == plan.id)).all()
    victim = assigned[0].device
    spare = db.scalar(select(Device).where(Device.agent_id == farm.info["id"], Device.id.notin_([a.device_id for a in assigned])))
    scheduler.tick_schedules(db)
    farm.provider.faults[victim.serial] = "offline"
    farm.agent.heartbeat()
    stats = scheduler.tick_devices(db, utcnow())
    assert stats["replaced"] == 0                                    # 기준 시간(30분) 전에는 대체하지 않음
    db.execute(Device.__table__.update().where(Device.id == victim.id).values(last_seen_at=utcnow() - timedelta(minutes=40)))
    db.commit()
    assert scheduler.tick_devices(db, utcnow())["replaced"] == 1
    db.expire_all()
    active = {a.device_id for a in db.scalars(select(DeviceAssignment).where(DeviceAssignment.plan_id == plan.id, DeviceAssignment.status == "active"))}
    assert victim.id not in active and spare.id in active and len(active) == 5
    farm.cycle()                                                     # 대체 기기가 대기 중이던 작업을 수행
    detail = client.get(f"/api/plans/{plan.id}", headers=customer.h).json()
    assert detail["total_runs"] == 5 and detail["passed"] == 5
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)
    farm.retire(db)


def test_pause_resume_cancel(client, admin, customer, mock_pg, farm, db):
    from app.models import TestJob
    from app.services import scheduler
    plan = paid_plan(client, customer, db)
    scheduler.tick_schedules(db)
    assert client.post(f"/api/admin/plans/{plan.id}/pause", headers=admin).json()["status"] == "paused"
    farm.agent.heartbeat()
    assert farm.api.claim(5) == []                                   # 일시정지 중에는 작업을 내주지 않음
    assert client.post(f"/api/admin/plans/{plan.id}/resume", headers=admin).json()["status"] == "running"
    jobs = farm.api.claim(5)
    assert len(jobs) == 5
    assert client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin).status_code == 200
    res = farm.agent.heartbeat()
    assert res is not None
    hb = client.post("/api/agent/heartbeat", headers={"X-Agent-Token": farm.cfg.token},
                     json={"devices": [], "running_jobs": [j["id"] for j in jobs]}).json()
    assert sorted(hb["cancel_jobs"]) == sorted(j["id"] for j in jobs)   # 에이전트에 취소 통지
    assert db.scalar(select(func.count()).select_from(TestJob).where(TestJob.plan_id == plan.id, TestJob.status == "cancelled")) == 5
    cmds = client.get("/api/admin/commands", headers=admin).json()
    assert any(c["type"] == "uninstall" and "정리" in c["params"].get("reason", "") for c in cmds)   # 검사 종료 후 고객 앱 정리


def test_full_cycle_completion_and_reports(client, admin, customer, mock_pg, farm, db):
    """결제 → 배정 → 반복 검사 → 기간 종료 → 최종 보고서 자동 생성 → 완료 알림 → 다운로드."""
    import io
    from openpyxl import load_workbook
    from app.db import utcnow
    from app.models import Order, Report, TestPlan
    from app.services import scheduler
    plan = paid_plan(client, customer, db, "STANDARD") if False else paid_plan(client, customer, db, "BASIC")
    now = utcnow()
    for day in range(3):
        scheduler.tick_schedules(db, now + timedelta(days=day, minutes=1))
        farm.cycle()
    assert scheduler.tick_finalize(db, now + timedelta(days=6, hours=12)) == 0          # 종료 24시간 전: 종료 예정 알림만
    assert scheduler.tick_finalize(db, now + timedelta(days=7, minutes=5)) == 1
    db.expire_all()
    plan = db.get(TestPlan, plan.id)
    assert plan.status == "completed" and db.get(Order, plan.order_id).status == "completed"
    events = [n["event"] for n in client.get("/api/notifications", headers=customer.h).json()["items"]]
    for ev in ("test_started", "test_ending", "test_completed", "report_issued"):
        assert ev in events, ev
    auto = db.scalars(select(Report).where(Report.plan_id == plan.id)).all()
    assert [(r.kind, r.fmt) for r in auto] == [("completion", "pdf")] and auto[0].is_mock
    pdf = client.get(f"/api/reports/{auto[0].id}/download", headers=customer.h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 20000
    assert b"NanumGothic" in pdf.content                                                # 한글 폰트 내장
    # BASIC은 Excel 미제공
    assert client.post(f"/api/plans/{plan.id}/reports", headers=customer.h, json={"kind": "daily", "fmt": "xlsx"}).status_code == 403
    for kind in ("comprehensive", "daily", "device", "version", "crash", "performance", "screenshot"):
        r = client.post(f"/api/plans/{plan.id}/reports", headers=customer.h, json={"kind": kind, "fmt": "pdf"})
        assert r.status_code == 200, (kind, r.text)
    # Excel(관리자 생성): 실제 DB 수치와 일치
    x = client.post("/api/admin/reports", headers=admin, json={"plan_id": plan.id, "kind": "completion", "fmt": "xlsx"}).json()
    wb = load_workbook(io.BytesIO(client.get(f"/api/reports/{x['id']}/download", headers=admin).content))
    overview = {row[0].value: row[1].value for row in wb["개요"].iter_rows()}
    assert overview["검사 횟수"] == 15 and overview["성공"] == 15 and overview["실제 검사 기기 수"] == 5
    assert "모의" in overview["구분"]
    assert [r[0].value for r in wb["일별"].iter_rows(min_row=2)] and wb["기기별"].max_row == 6
    listed = client.get("/api/reports", headers=customer.h).json()["items"]
    assert len(listed) == 9


def test_play_flow_install_request_period_start_and_update(client, admin, customer, mock_pg, farm, db):
    """Play 스토어 배포본: 설치 요청 → 기준 대수 설치 시 검사 기간 시작 → 스토어 새 버전 자동 업데이트 표시."""
    from app.models import TestPlan
    from app.services import scheduler
    from gat_engine.providers import MockProvider
    app = client.post("/api/apps", headers=customer.h, json={"package_name": f"com.playflow.a{__import__('uuid').uuid4().hex[:8]}", "name": "플레이앱", "ownership_confirmed": True}).json()
    pkg = app["package_name"]
    order = customer.order(app, app["versions"][0])
    assert customer.pay(order)[0].status_code == 200
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))
    assert plan.status == "scheduled" and plan.period_started is False
    MockProvider.store_version[pkg] = "1.0.0"
    req = client.post(f"/api/plans/{plan.id}/install-request", headers=customer.h)
    assert req.status_code == 200 and req.json()["jobs_created"] == 5
    assert client.post(f"/api/plans/{plan.id}/install-request", headers=customer.h).status_code == 409   # 진행 중에는 중복 요청 불가
    farm.cycle()
    db.expire_all()
    plan = db.get(TestPlan, plan.id)
    assert plan.period_started is True and (plan.end_at - plan.start_at).days == 7
    ov = client.get(f"/api/apps/{app['id']}/overview", headers=customer.h).json()
    assert ov["installed_devices"] == 5 and ov["install_threshold"] == 5 and ov["version"]["installed"] == "1.0.0"
    assert all(c["updated"] is False for c in ov["days"][0]["cells"])
    MockProvider.store_version[pkg] = "1.1.0"                               # 고객이 스토어에 새 버전 출시
    assert client.post(f"/api/plans/{plan.id}/install-request", headers=customer.h).json()["jobs_created"] == 5
    farm.cycle()
    ov = client.get(f"/api/apps/{app['id']}/overview", headers=customer.h).json()
    assert ov["version"]["installed"] == "1.1.0" and all(c["updated"] for c in ov["days"][0]["cells"])
    res = client.get(f"/api/plans/{plan.id}/results", headers=customer.h).json()
    assert any("1.0.0 → 1.1.0" in s["actual"] for s in res[0]["steps"])
    from conftest import Cust
    assert client.post(f"/api/plans/{plan.id}/install-request", headers=Cust(client).h).status_code == 404
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)
    MockProvider.store_version.clear()


def test_single_plan_price_refund_and_free_extension(client, admin, customer, mock_pg, farm, db):
    """단일 요금제 8,000원·18일·16대, 시작 전 전액 환불, 시작 후 환불 불가, 2회 업데이트 시 18일 무료 연장."""
    from app.models import Order, Payment, TestPlan
    from gat_engine.providers import MockProvider
    p = {x["code"]: x for x in client.get("/api/public/products").json()}["CLOSED18"]
    assert (p["price"], p["duration_days"], p["device_count"], p["daily_runs"]) == (8000, 18, 16, 1)
    refund_doc = client.get("/api/public/legal/refund").json()
    assert "8,000원" in refund_doc["body"] and "TWA" in refund_doc["body"]

    def new_order():
        app = client.post("/api/apps", headers=customer.h, json={"package_name": f"com.policy.a{__import__('uuid').uuid4().hex[:8]}", "name": "정책앱", "ownership_confirmed": True}).json()
        order = customer.order(app, app["versions"][0])           # BASIC: 기기 5대 → 기준 대수 5
        assert customer.pay(order)[0].status_code == 200
        return app, order, db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))

    # 1) 테스트 시작 전: 고객이 직접 전액 환불
    app, order, plan = new_order()
    assert client.get(f"/api/apps/{app['id']}/overview", headers=customer.h).json()["refundable"] is True
    r = client.post(f"/api/orders/{order['id']}/refund-request", headers=customer.h)
    assert r.status_code == 200 and r.json()["amount"] == order["final_amount"]
    db.expire_all()
    assert db.get(Order, order["id"]).status == "refunded" and db.get(TestPlan, plan.id).status == "cancelled"
    assert db.scalar(select(Payment).where(Payment.order_id == order["id"])).status == "refunded"
    assert client.post(f"/api/orders/{order['id']}/refund-request", headers=customer.h).status_code == 400

    # 2) 테스트 시작 후: 환불 불가, 업데이트 2회 미만이면 연장 불가
    app, order, plan = new_order()
    pkg = app["package_name"]
    for ver in ("1.0.0",):
        MockProvider.store_version[pkg] = ver
        client.post(f"/api/plans/{plan.id}/install-request", headers=customer.h)
        farm.cycle()
    assert client.post(f"/api/orders/{order['id']}/refund-request", headers=customer.h).status_code == 400
    assert client.post(f"/api/plans/{plan.id}/extend", headers=customer.h).status_code == 400
    for ver in ("1.1.0", "1.2.0"):
        MockProvider.store_version[pkg] = ver
        assert client.post(f"/api/plans/{plan.id}/install-request", headers=customer.h).status_code == 200
        farm.cycle()
    ov = client.get(f"/api/apps/{app['id']}/overview", headers=customer.h).json()
    assert ov["updates"] == 2 and ov["can_extend"] is True and ov["refundable"] is False
    db.expire_all()
    before = db.get(TestPlan, plan.id).end_at
    assert client.post(f"/api/plans/{plan.id}/extend", headers=customer.h).status_code == 200
    db.expire_all()
    assert (db.get(TestPlan, plan.id).end_at - before).days == 18
    assert client.post(f"/api/plans/{plan.id}/extend", headers=customer.h).status_code == 400      # 1회만
    from conftest import Cust
    other = Cust(client)
    assert client.post(f"/api/plans/{plan.id}/extend", headers=other.h).status_code == 404
    assert client.post(f"/api/orders/{order['id']}/refund-request", headers=other.h).status_code == 404
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)
    MockProvider.store_version.clear()
