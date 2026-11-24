"""검사 스케줄러. 모든 상태는 DB에 있으므로 서버가 재시작되어도 일정과 작업이 보존·복구된다."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..models import (Agent, Customer, Device, DeviceAssignment, DeviceCommand, DeviceHeartbeat, Notification,
                      Order, Report, TestJob, TestPlan, TestSchedule)
from . import orders as order_svc
from . import settings_store
from .audit import syslog
from .notifications import notify, notify_staff, process_email_queue
from .results import retry_or_fail

log = logging.getLogger("gat.scheduler")
OFFLINE_AFTER = timedelta(seconds=120)


def _owner(db: Session, plan: TestPlan) -> int:
    return db.get(Customer, plan.customer_id).user_id


def next_run(plan: TestPlan, sched: TestSchedule, after: datetime) -> datetime:
    """다음 실행 시각. run_times(특정 시간, UTC 'HH:MM')가 있으면 그 시각, 없으면 24h/일일횟수 간격."""
    times = sorted(t for t in (sched.run_times or []) if isinstance(t, str) and len(t) == 5)
    if times:
        for day in range(0, 3):
            base = (after + timedelta(days=day)).replace(second=0, microsecond=0)
            for t in times:
                cand = base.replace(hour=int(t[:2]), minute=int(t[3:]))
                if cand > after:
                    return cand
    return after + timedelta(hours=24 / max(1, plan.daily_runs))


def tick_allocate(db: Session) -> int:
    done = 0
    plans = db.scalars(select(TestPlan).where(TestPlan.status == "waiting_devices")
                       .order_by(TestPlan.priority.desc(), TestPlan.id).with_for_update(of=TestPlan, skip_locked=True)).all()
    for plan in plans:
        done += 1 if order_svc.allocate_plan(db, plan) else 0
    db.commit()
    return done


def tick_schedules(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    created = 0
    rows = db.scalars(select(TestSchedule).where(TestSchedule.status == "active", TestSchedule.next_run_at <= now)
                      .with_for_update(of=TestSchedule, skip_locked=True)).all()
    for sched in rows:
        plan = db.get(TestPlan, sched.plan_id)
        if plan.status not in ("scheduled", "running") or plan.start_at > now:
            continue
        if sched.next_run_at >= plan.end_at:
            sched.status, sched.next_run_at = "done", None
            continue
        run_key = sched.next_run_at.strftime("%Y%m%dT%H%M")
        created += order_svc.create_jobs_for_run(db, plan, run_key)
        if plan.status == "scheduled":
            plan.status, plan.order.status = "running", "running"
            notify(db, _owner(db, plan), "test_started",
                   {"app": plan.app.name, "end": plan.end_at.strftime("%Y-%m-%d")}, f"/dashboard/orders/{plan.order_id}")
        sched.last_run_at = sched.next_run_at
        nxt = next_run(plan, sched, sched.next_run_at)
        while nxt <= now:  # 서버 중단 등으로 밀린 회차는 건너뛴다(중복·폭주 방지)
            nxt = next_run(plan, sched, nxt)
        sched.next_run_at = nxt
    db.commit()
    return created


def tick_leases(db: Session, now: datetime | None = None) -> int:
    """임대 시간이 만료된 작업 회수(에이전트 종료·검사 중 강제 종료·타임아웃)."""
    now = now or utcnow()
    jobs = db.scalars(select(TestJob).where(TestJob.status.in_(["leased", "running"]), TestJob.lease_expires_at < now)
                      .with_for_update(of=TestJob, skip_locked=True)).all()
    for job in jobs:
        retry_or_fail(db, job, "작업 타임아웃(임대 시간 만료)", final_status="timeout")
    db.commit()
    return len(jobs)


def device_status(db: Session, dev: Device, busy: bool | None = None) -> str:
    if not dev.enabled:
        return "disabled"
    if dev.maintenance:
        return "maintenance"
    if dev.conn_state == "unauthorized":
        return "error"
    if dev.conn_state != "device":
        return "offline"
    if dev.temperature and dev.temperature >= settings_store.get_int(db, "limits.temp_overheat"):
        return "overheat"
    if dev.storage_total_mb and dev.storage_free_mb < settings_store.get_int(db, "limits.storage_low_mb"):
        return "low_storage"
    if busy is None:
        busy = bool(db.scalar(select(TestJob.id).where(TestJob.device_id == dev.id,
                                                       TestJob.status.in_(["leased", "running"])).limit(1)))
    if busy:
        return "testing"
    assigned = db.scalar(select(DeviceAssignment.id).join(TestPlan, TestPlan.id == DeviceAssignment.plan_id)
                         .where(DeviceAssignment.device_id == dev.id, DeviceAssignment.status == "active",
                                TestPlan.status.in_(order_svc.ACTIVE_PLAN)).limit(1))
    return "assigned" if assigned else "idle"


def tick_devices(db: Session, now: datetime | None = None) -> dict:
    """연결 끊김 감지 + 장시간 오프라인 기기의 대체 기기 배정."""
    now = now or utcnow()
    stats = {"agents_offline": 0, "devices_offline": 0, "replaced": 0}
    for agent in db.scalars(select(Agent).where(Agent.status == "online", Agent.last_seen_at < now - OFFLINE_AFTER)):
        agent.status = "offline"
        stats["agents_offline"] += 1
        notify_staff(db, "device_disconnected", {"target": f"PC 에이전트 '{agent.name}'"}, "/admin/agents")
        syslog(db, "warn", "agent", f"에이전트 연결 끊김: {agent.name} ({agent.uid})")
    for dev in db.scalars(select(Device).where(Device.conn_state == "device", Device.last_seen_at < now - OFFLINE_AFTER)):
        dev.conn_state, dev.status = "offline", device_status(db, dev) if not dev.enabled or dev.maintenance else "offline"
        stats["devices_offline"] += 1
        notify_staff(db, "device_disconnected", {"target": f"기기 '{dev.name or dev.serial}'"}, "/admin/devices")
    limit = now - timedelta(minutes=settings_store.get_int(db, "limits.device_offline_replace_min"))
    bad = db.scalars(select(DeviceAssignment).join(Device, Device.id == DeviceAssignment.device_id)
                     .join(TestPlan, TestPlan.id == DeviceAssignment.plan_id)
                     .where(DeviceAssignment.status == "active", TestPlan.status.in_(["scheduled", "running"]),
                            ((Device.status.in_(["offline", "error", "disabled", "maintenance"])) &
                             ((Device.last_seen_at < limit) | (Device.last_seen_at.is_(None))))
                            | (Device.enabled.is_(False)) | (Device.maintenance.is_(True)))).unique().all()
    for assign in bad:
        plan = db.get(TestPlan, assign.plan_id)
        taken = select(DeviceAssignment.device_id).where(DeviceAssignment.plan_id == plan.id)
        sub = db.scalar(select(Device).where(Device.enabled.is_(True), Device.maintenance.is_(False),
                                             Device.is_mock == plan.is_mock, Device.status.in_(["idle", "assigned", "testing"]),
                                             Device.id.notin_(taken)).order_by(Device.id).limit(1)
                        .with_for_update(of=Device, skip_locked=True))
        if not sub:
            continue
        assign.status, assign.released_at = "replaced", now
        db.add(DeviceAssignment(plan_id=plan.id, device_id=sub.id))
        for job in db.scalars(select(TestJob).where(TestJob.plan_id == plan.id, TestJob.device_id == assign.device_id,
                                                    TestJob.status == "queued")):
            clash = db.scalar(select(TestJob.id).where(TestJob.plan_id == plan.id, TestJob.device_id == sub.id,
                                                       TestJob.run_key == job.run_key))
            if clash:
                job.status, job.finished_at, job.error = "cancelled", now, "대체 기기에 동일 회차 존재"
            else:
                job.device_id, job.agent_id = sub.id, sub.agent_id
        stats["replaced"] += 1
        syslog(db, "warn", "scheduler", f"대체 기기 배정: plan={plan.id} device {assign.device_id} → {sub.id}")
    db.commit()
    return stats


def tick_finalize(db: Session, now: datetime | None = None) -> int:
    """검사 기간 종료 처리: 최종 보고서 자동 생성 + 완료 알림."""
    from .reports import generate_report
    now = now or utcnow()
    done = 0
    soon = db.scalars(select(TestPlan).where(TestPlan.status == "running", TestPlan.ending_notified.is_(False),
                                             TestPlan.end_at <= now + timedelta(hours=24), TestPlan.end_at > now)).all()
    for plan in soon:
        plan.ending_notified = True
        notify(db, _owner(db, plan), "test_ending", {"app": plan.app.name, "end": plan.end_at.strftime("%Y-%m-%d %H:%M UTC")},
               f"/dashboard/orders/{plan.order_id}")
    plans = db.scalars(select(TestPlan).where(TestPlan.status.in_(["scheduled", "running"]), TestPlan.end_at <= now)
                       .with_for_update(of=TestPlan, skip_locked=True)).all()
    for plan in plans:
        active = db.scalar(select(func.count()).select_from(TestJob).where(
            TestJob.plan_id == plan.id, TestJob.status.in_(["leased", "running"])))
        if active and plan.end_at > now - timedelta(hours=2):
            continue  # 진행 중인 마지막 작업이 끝나기를 잠시 기다린다
        order_svc.stop_plan(db, plan, "completed")
        order = db.get(Order, plan.order_id)
        order.status, order.completed_at = "completed", now
        owner = _owner(db, plan)
        notify(db, owner, "test_completed", {"app": plan.app.name}, f"/dashboard/orders/{order.id}")
        snap = order.product_snapshot or {}
        formats = (["pdf"] if snap.get("pdf_report", True) else []) + (["xlsx"] if snap.get("excel_report") else [])
        for fmt in formats:
            try:
                rep = generate_report(db, plan, "completion", fmt)
                notify(db, owner, "report_issued", {"app": plan.app.name, "report_no": rep.report_no}, "/dashboard/reports")
            except Exception as exc:  # noqa: BLE001
                syslog(db, "error", "report", f"최종 보고서 생성 실패 plan={plan.id}: {exc}")
                notify_staff(db, "test_error", {"app": plan.app.name, "reason": f"최종 보고서 생성 실패: {exc}"[:200]})
        done += 1
    db.commit()
    return done


def tick_cleanup(db: Session, now: datetime | None = None) -> None:
    now = now or utcnow()
    db.execute(DeviceHeartbeat.__table__.delete().where(DeviceHeartbeat.created_at < now - timedelta(days=7)))
    db.execute(DeviceCommand.__table__.update().where(DeviceCommand.status.in_(["queued", "sent"]),
                                                      DeviceCommand.created_at < now - timedelta(hours=24))
               .values(status="expired", finished_at=now))
    days = settings_store.get_int(db, "retention.days")
    db.execute(Notification.__table__.delete().where(Notification.created_at < now - timedelta(days=days)))
    db.commit()


def run_all() -> None:
    """APScheduler가 주기 호출. advisory lock으로 다중 인스턴스 중복 실행을 방지한다."""
    with SessionLocal() as db:
        got = db.scalar(text("select pg_try_advisory_lock(727001)"))
        if not got:
            return
        try:
            for fn in (tick_allocate, tick_schedules, tick_leases, tick_devices, tick_finalize, process_email_queue):
                try:
                    fn(db)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    log.exception("scheduler tick failed: %s", fn.__name__)
                    syslog(db, "error", "scheduler", f"{fn.__name__} 실패: {exc}")
                    db.commit()
        finally:
            db.execute(text("select pg_advisory_unlock(727001)"))
            db.commit()


def run_cleanup() -> None:
    with SessionLocal() as db:
        tick_cleanup(db)


_scheduler = None


def start() -> None:
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(run_all, "interval", seconds=20, max_instances=1, coalesce=True, id="tick")
    _scheduler.add_job(run_cleanup, "interval", hours=6, max_instances=1, coalesce=True, id="cleanup")
    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
