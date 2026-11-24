"""관리자: 장비 관리 + 검사 관리."""
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..deps import client_ip, require_perm
from ..hub import hub
from ..models import (Agent, AgentToken, App, AppFile, AppVersion, CrashLog, Customer, Device, DeviceAssignment,
                      DeviceCommand, DeviceGroup, DeviceHeartbeat, Report, Screenshot, SystemLog, TestJob, TestPlan,
                      TestResult, TestScenario, TestSchedule, User)
from ..security import new_token
from ..services import analysis, settings_store, storage
from ..services import orders as order_svc
from ..services.audit import audit
from ..services.reports import KINDS, generate_report
from ..services.scheduler import device_status
from .admin import register_crud, row_dict, router as _admin_router
from .customer import file_url, plan_brief, report_view, scenario_view, validate_steps

router = APIRouter(prefix="/api/admin", tags=["admin-devices"])
PACKAGE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
# 승인된 원격 명령만 허용한다. 임의 셸 명령 실행 기능은 제공하지 않는다.
COMMANDS = {"screenshot", "install_apk", "uninstall", "launch", "stop", "app_version", "storage", "status",
            "reconnect", "reboot", "push_file", "run_scenario"}

register_crud("/device-groups", DeviceGroup, "devices", ["name", "description"], order=[DeviceGroup.name])


# ---------------- PC 에이전트 ----------------
def agent_view(db: Session, a: Agent) -> dict:
    devices = db.scalar(select(func.count()).select_from(Device).where(Device.agent_id == a.id)) or 0
    online = db.scalar(select(func.count()).select_from(Device).where(Device.agent_id == a.id, Device.conn_state == "device")) or 0
    tokens = db.scalars(select(AgentToken).where(AgentToken.agent_id == a.id).order_by(AgentToken.id.desc()).limit(5)).all()
    return {"id": a.id, "uid": a.uid, "name": a.name, "kind": a.kind, "hostname": a.hostname, "os": a.os, "version": a.version,
            "status": a.status, "last_seen_at": a.last_seen_at, "ip": a.ip, "created_at": a.created_at,
            "devices": devices, "devices_online": online, "ws_connected": hub.connected(a.id),
            "enroll_pending": bool(a.enroll_code_hash and a.enroll_expires_at and a.enroll_expires_at > utcnow()),
            "tokens": [{"id": t.id, "created_at": t.created_at, "expires_at": t.expires_at, "revoked_at": t.revoked_at,
                        "active": not t.revoked_at and t.expires_at > utcnow()} for t in tokens]}


def _new_code(agent: Agent) -> str:
    plain, hashed = new_token(18)
    agent.enroll_code_hash, agent.enroll_expires_at = hashed, utcnow() + timedelta(hours=24)
    return plain


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "real"


@router.get("/agents")
def agents(db: Session = Depends(get_db), _: User = Depends(require_perm("devices"))):
    return [agent_view(db, a) for a in db.scalars(select(Agent).order_by(Agent.id.desc()))]


@router.post("/agents")
def create_agent(body: AgentIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    """에이전트 등록: 고유 ID와 1회용 등록 코드(24시간 유효)를 발급한다. 코드는 이 응답에서만 보인다."""
    agent = Agent(uid="AG-" + secrets.token_hex(6).upper(), name=body.name, kind="mock" if body.kind == "mock" else "real")
    code = _new_code(agent)
    db.add(agent)
    db.flush()
    audit(db, user.id, "agent.create", "agent", agent.id, {"kind": agent.kind}, client_ip(request))
    db.commit()
    return {**agent_view(db, agent), "enroll_code": code}


@router.post("/agents/{aid}/enroll-code")
def reissue_code(aid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    agent = db.get(Agent, aid)
    if not agent or agent.status == "revoked":
        raise HTTPException(404, "에이전트를 찾을 수 없습니다.")
    code = _new_code(agent)
    audit(db, user.id, "agent.reissue_code", "agent", aid, ip=client_ip(request))
    db.commit()
    return {"enroll_code": code}


@router.post("/agents/{aid}/revoke")
def revoke_agent(aid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    """인증키 전체 폐기 + 에이전트 사용 중지."""
    agent = db.get(Agent, aid)
    if not agent:
        raise HTTPException(404, "에이전트를 찾을 수 없습니다.")
    db.execute(update(AgentToken).where(AgentToken.agent_id == aid, AgentToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    agent.status, agent.enroll_code_hash = "revoked", None
    for dev in db.scalars(select(Device).where(Device.agent_id == aid)):
        dev.conn_state, dev.status = "offline", "offline"
    audit(db, user.id, "agent.revoke", "agent", aid, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/agents/{aid}/tokens/{tid}/revoke")
def revoke_token(aid: int, tid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    tok = db.get(AgentToken, tid)
    if not tok or tok.agent_id != aid:
        raise HTTPException(404, "인증키를 찾을 수 없습니다.")
    tok.revoked_at = utcnow()
    audit(db, user.id, "agent.revoke_token", "agent", aid, {"token_id": tid}, client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/agent-downloads")
def agent_downloads(db: Session = Depends(get_db), _: User = Depends(require_perm("devices"))):
    repo = settings.AGENT_DOWNLOAD_REPO
    base = f"https://github.com/{repo}/releases/latest/download"
    return {"latest_version": settings_store.get(db, "agent.latest_version"), "releases_url": f"https://github.com/{repo}/releases",
            "files": [{"os": "Windows", "name": "GoogleAutoTesterAgent-Setup.exe", "url": f"{base}/GoogleAutoTesterAgent-Setup.exe"},
                      {"os": "Windows (무설치)", "name": "GoogleAutoTesterAgent-windows.zip", "url": f"{base}/GoogleAutoTesterAgent-windows.zip"},
                      {"os": "Linux", "name": "google-auto-tester-agent-linux.tar.gz", "url": f"{base}/google-auto-tester-agent-linux.tar.gz"}],
            "note": "설치 파일은 GitHub Actions가 릴리스 태그에서 빌드해 GitHub Releases에 등록합니다."}


# ---------------- 기기 ----------------
def device_view(d: Device, job: TestJob | None = None, plans: int = 0) -> dict:
    return {"id": d.id, "agent_id": d.agent_id, "agent_name": d.agent.name, "serial": d.serial, "name": d.name,
            "group_id": d.group_id, "group": d.group.name if d.group else None, "manufacturer": d.manufacturer,
            "model": d.model, "android_version": d.android_version, "sdk": d.sdk, "cpu": d.cpu, "ram_mb": d.ram_mb,
            "storage_total_mb": d.storage_total_mb, "storage_free_mb": d.storage_free_mb, "battery": d.battery,
            "temperature": d.temperature, "resolution": d.resolution, "network": d.network, "conn_state": d.conn_state,
            "status": d.status, "enabled": d.enabled, "maintenance": d.maintenance,
            "google_account_confirmed": d.google_account_confirmed, "is_mock": d.is_mock, "installed_apps": d.installed_apps or {},
            "last_seen_at": d.last_seen_at, "last_test_at": d.last_test_at, "notes": d.notes, "active_plans": plans,
            "current_job": {"id": job.id, "progress": job.progress, "package": (job.payload or {}).get("package"),
                            "plan_id": job.plan_id} if job else None}


@router.get("/devices")
def devices(status: str = "", group_id: int | None = None, mock: bool | None = None, db: Session = Depends(get_db),
            _: User = Depends(require_perm("devices"))):
    stmt = select(Device)
    if status:
        stmt = stmt.where(Device.status == status)
    if group_id:
        stmt = stmt.where(Device.group_id == group_id)
    if mock is not None:
        stmt = stmt.where(Device.is_mock.is_(mock))
    rows = db.scalars(stmt.order_by(Device.agent_id, Device.name, Device.id).limit(3000)).unique().all()
    jobs = {j.device_id: j for j in db.scalars(select(TestJob).where(TestJob.status.in_(["leased", "running"])))}
    loads = dict(db.execute(select(DeviceAssignment.device_id, func.count()).join(TestPlan, TestPlan.id == DeviceAssignment.plan_id)
                            .where(DeviceAssignment.status == "active", TestPlan.status.in_(order_svc.ACTIVE_PLAN))
                            .group_by(DeviceAssignment.device_id)).all())
    counts = dict(db.execute(select(Device.status, func.count()).group_by(Device.status)).all())
    return {"counts": counts, "items": [device_view(d, jobs.get(d.id), loads.get(d.id, 0)) for d in rows]}


@router.get("/devices/{did}")
def device_detail(did: int, db: Session = Depends(get_db), _: User = Depends(require_perm("devices"))):
    d = db.get(Device, did)
    if not d:
        raise HTTPException(404, "기기를 찾을 수 없습니다.")
    beats = db.scalars(select(DeviceHeartbeat).where(DeviceHeartbeat.device_id == did).order_by(DeviceHeartbeat.id.desc()).limit(288)).all()
    cmds = db.scalars(select(DeviceCommand).where(DeviceCommand.device_id == did).order_by(DeviceCommand.id.desc()).limit(30)).all()
    assigns = db.execute(select(DeviceAssignment, TestPlan).join(TestPlan, TestPlan.id == DeviceAssignment.plan_id)
                         .where(DeviceAssignment.device_id == did).order_by(DeviceAssignment.id.desc()).limit(30)).all()
    results = db.scalars(select(TestResult).where(TestResult.device_id == did).order_by(TestResult.id.desc()).limit(30)).all()
    job = db.scalar(select(TestJob).where(TestJob.device_id == did, TestJob.status.in_(["leased", "running"])))
    return {"device": device_view(d, job),
            "heartbeats": [{"at": b.created_at, "battery": b.battery, "temperature": b.temperature,
                            "storage_free_mb": b.storage_free_mb, "status": b.status} for b in reversed(beats)],
            "commands": [command_view(c) for c in cmds],
            "assignments": [{"plan_id": p.id, "app": p.app.name, "status": a.status, "plan_status": p.status,
                             "assigned_at": a.assigned_at, "released_at": a.released_at} for a, p in assigns],
            "results": [{"id": r.id, "status": r.status, "plan_id": r.plan_id, "created_at": r.created_at,
                         "crash_count": r.crash_count} for r in results]}


class DevicePatch(BaseModel):
    name: str | None = None
    group_id: int | None = None
    clear_group: bool = False
    enabled: bool | None = None
    maintenance: bool | None = None
    google_account_confirmed: bool | None = None
    notes: str | None = None


@router.patch("/devices/{did}")
def patch_device(did: int, body: DevicePatch, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_perm("devices"))):
    d = db.get(Device, did)
    if not d:
        raise HTTPException(404, "기기를 찾을 수 없습니다.")
    data = body.model_dump(exclude_none=True, exclude={"clear_group"})
    for k, v in data.items():
        setattr(d, k, v)
    if body.clear_group:
        d.group_id = None
    db.flush()
    d.status = device_status(db, d)
    audit(db, user.id, "device.update", "device", did, data, client_ip(request))
    db.commit()
    return device_view(d)


@router.delete("/devices/{did}")
def delete_device(did: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    d = db.get(Device, did)
    if not d:
        raise HTTPException(404, "기기를 찾을 수 없습니다.")
    if db.scalar(select(TestResult.id).where(TestResult.device_id == did).limit(1)) or \
            db.scalar(select(DeviceAssignment.id).where(DeviceAssignment.device_id == did).limit(1)):
        raise HTTPException(409, "검사 이력이 있는 기기는 삭제할 수 없습니다. '사용 중지'를 이용해 주세요.")
    db.delete(d)
    audit(db, user.id, "device.delete", "device", did, ip=client_ip(request))
    db.commit()
    return {"ok": True}


# ---------------- 원격 제어 ----------------
def command_view(c: DeviceCommand) -> dict:
    result = dict(c.result or {})
    if result.get("screenshot_id"):
        result["screenshot_url"] = file_url("screenshot", result["screenshot_id"])
    return {"id": c.id, "device_id": c.device_id, "type": c.type, "params": c.params, "status": c.status, "result": result,
            "created_at": c.created_at, "finished_at": c.finished_at}


class CommandIn(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=1000)
    type: str
    params: dict = {}


@router.post("/commands")
def send_commands(body: CommandIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    if body.type not in COMMANDS:
        raise HTTPException(400, "승인되지 않은 명령입니다.")
    params: dict = {}
    if body.type in ("uninstall", "launch", "stop", "app_version"):
        pkg = str(body.params.get("package", ""))
        if not PACKAGE_RE.match(pkg) or not db.scalar(select(App.id).where(App.package_name == pkg, App.deleted_at.is_(None))):
            raise HTTPException(400, "등록된 검사 대상 앱의 패키지명만 사용할 수 있습니다.")
        params = {"package": pkg}
    elif body.type == "install_apk":
        version = db.get(AppVersion, int(body.params.get("app_version_id") or 0))
        if not version or not version.file or version.file.status != "clean":
            raise HTTPException(400, "설치 가능한(격리되지 않은) APK가 있는 앱 버전을 선택해 주세요.")
        params = {"file_id": version.file.id, "sha256": version.file.sha256, "package": db.get(App, version.app_id).package_name}
    elif body.type == "push_file":
        f = db.get(AppFile, int(body.params.get("file_id") or 0))
        if not f or f.kind != "transfer":
            raise HTTPException(400, "전송할 파일을 먼저 업로드해 주세요.")
        params = {"file_id": f.id, "sha256": f.sha256, "filename": f.filename}
    elif body.type == "run_scenario":
        sc = db.get(TestScenario, int(body.params.get("scenario_id") or 0))
        pkg = str(body.params.get("package", ""))
        if not sc or not PACKAGE_RE.match(pkg):
            raise HTTPException(400, "시나리오와 패키지명을 확인해 주세요.")
        params = {"package": pkg, "steps": sc.steps, "scenario_id": sc.id}
    devs = db.scalars(select(Device).where(Device.id.in_(body.device_ids))).unique().all()
    out, agents = [], set()
    for d in devs:
        cmd = DeviceCommand(device_id=d.id, agent_id=d.agent_id, type=body.type, params=params, created_by=user.id)
        db.add(cmd)
        out.append(cmd)
        agents.add(d.agent_id)
    audit(db, user.id, "device.command", "device", ",".join(str(d.id) for d in devs)[:60],
          {"type": body.type, "params": {k: v for k, v in params.items() if k != "steps"}, "count": len(devs)}, client_ip(request))
    db.commit()
    for aid in agents:
        hub.wake(aid, "command")
    return [command_view(c) for c in out]


@router.get("/commands")
def commands(ids: str = "", device_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_perm("devices"))):
    stmt = select(DeviceCommand)
    if ids:
        stmt = stmt.where(DeviceCommand.id.in_([int(i) for i in ids.split(",") if i.isdigit()]))
    if device_id:
        stmt = stmt.where(DeviceCommand.device_id == device_id)
    return [command_view(c) for c in db.scalars(stmt.order_by(DeviceCommand.id.desc()).limit(200))]


@router.post("/transfer-files")
async def upload_transfer(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_perm("devices"))):
    """기기로 전송할 파일 업로드(50MB 이하)."""
    name = (file.filename or "file").replace("/", "_").replace("\\", "_")[:120]
    rel, size, sha = await storage.save_upload(file, "tmp", "", 50 * 1024 * 1024)
    customer = db.scalar(select(Customer.id).limit(1))
    if customer is None:
        storage.remove(rel)
        raise HTTPException(400, "고객 데이터가 없어 파일 소유자를 지정할 수 없습니다.")
    row = AppFile(customer_id=customer, kind="transfer", filename=name, path=rel, size=size, sha256=sha)
    db.add(row)
    db.commit()
    return {"file_id": row.id, "filename": name, "size": size}


@router.get("/incidents")
def incidents(db: Session = Depends(get_db), _: User = Depends(require_perm("devices"))):
    """장비 장애 관리: 문제 상태 기기 + 오프라인 에이전트 + 관련 시스템 로그."""
    bad = db.scalars(select(Device).where(Device.status.in_(["offline", "error", "overheat", "low_storage"]), Device.enabled.is_(True))
                     .order_by(Device.last_seen_at.desc().nullslast()).limit(300)).unique().all()
    agents_off = db.scalars(select(Agent).where(Agent.status == "offline")).all()
    logs = db.scalars(select(SystemLog).where(SystemLog.source.in_(["agent", "scheduler", "device"]), SystemLog.level.in_(["warn", "error"]))
                      .order_by(SystemLog.id.desc()).limit(100)).all()
    return {"devices": [device_view(d) for d in bad], "agents": [agent_view(db, a) for a in agents_off],
            "logs": [row_dict(r) for r in logs]}


# ---------------- 검사 작업 / 스케줄 ----------------
def job_view(j: TestJob) -> dict:
    return {"id": j.id, "plan_id": j.plan_id, "device_id": j.device_id, "device": j.device.name or j.device.serial,
            "package": (j.payload or {}).get("package"), "run_key": j.run_key, "kind": j.kind, "status": j.status,
            "priority": j.priority, "attempts": j.attempts, "max_attempts": j.max_attempts, "progress": j.progress,
            "next_attempt_at": j.next_attempt_at, "lease_expires_at": j.lease_expires_at, "started_at": j.started_at,
            "finished_at": j.finished_at, "error": j.error, "is_mock": j.is_mock, "created_at": j.created_at}


@router.get("/jobs")
def jobs(status: str = "", plan_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    stmt = select(TestJob)
    if status:
        stmt = stmt.where(TestJob.status.in_(status.split(",")))
    if plan_id:
        stmt = stmt.where(TestJob.plan_id == plan_id)
    counts = dict(db.execute(select(TestJob.status, func.count()).group_by(TestJob.status)).all())
    return {"counts": counts, "items": [job_view(j) for j in db.scalars(stmt.order_by(TestJob.id.desc()).limit(500)).unique()]}


@router.post("/jobs/{jid}/{action}")
def job_action(jid: int, action: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("tests"))):
    job = db.scalar(select(TestJob).where(TestJob.id == jid).with_for_update(of=TestJob))
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    if action == "cancel":
        if job.status not in ("queued", "leased", "running"):
            raise HTTPException(400, "취소할 수 없는 상태입니다.")
        job.status, job.finished_at, job.error, job.lease_token = "cancelled", utcnow(), "관리자 취소", None
    elif action == "retry":
        if job.status not in ("failed", "timeout", "cancelled"):
            raise HTTPException(400, "재시도할 수 없는 상태입니다.")
        if db.scalar(select(TestResult.id).where(TestResult.job_id == job.id)):
            db.execute(TestResult.__table__.delete().where(TestResult.job_id == job.id))
        job.status, job.attempts, job.next_attempt_at, job.finished_at, job.error = "queued", 0, utcnow(), None, ""
        hub.wake(job.agent_id)
    else:
        raise HTTPException(400, "지원하지 않는 동작입니다.")
    audit(db, user.id, f"job.{action}", "job", jid, ip=client_ip(request))
    db.commit()
    return job_view(job)


def admin_plan_view(db: Session, p: TestPlan) -> dict:
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == p.id))
    return {**plan_brief(db, p), "app": p.app.name, "package_name": p.app.package_name, "order_no": p.order.order_no,
            "order_id": p.order_id, "customer_id": p.customer_id, "priority": p.priority,
            "run_times": sched.run_times if sched else [], "schedule_status": sched.status if sched else None}


@router.get("/plans")
def plans(status: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    stmt = select(TestPlan)
    if status:
        stmt = stmt.where(TestPlan.status.in_(status.split(",")))
    return [admin_plan_view(db, p) for p in db.scalars(stmt.order_by(TestPlan.id.desc()).limit(300))]


class PlanPatch(BaseModel):
    daily_runs: int | None = Field(None, ge=1, le=24)
    run_times: list[str] | None = None
    priority: int | None = None


@router.patch("/plans/{pid}")
def patch_plan(pid: int, body: PlanPatch, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("tests"))):
    plan = db.get(TestPlan, pid)
    if not plan:
        raise HTTPException(404, "검사 계획을 찾을 수 없습니다.")
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == pid))
    if body.daily_runs:
        plan.daily_runs = body.daily_runs
    if body.priority is not None:
        plan.priority = body.priority
    if body.run_times is not None:
        if any(not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t) for t in body.run_times):
            raise HTTPException(400, "시간은 HH:MM(UTC) 형식이어야 합니다.")
        sched.run_times = sorted(set(body.run_times))
    audit(db, user.id, "plan.update", "plan", pid, body.model_dump(exclude_none=True), client_ip(request))
    db.commit()
    return admin_plan_view(db, plan)


@router.post("/plans/{pid}/{action}")
def plan_action(pid: int, action: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("tests"))):
    plan = db.scalar(select(TestPlan).where(TestPlan.id == pid).with_for_update(of=TestPlan))
    if not plan:
        raise HTTPException(404, "검사 계획을 찾을 수 없습니다.")
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == pid))
    if action == "pause":
        if plan.status not in ("scheduled", "running"):
            raise HTTPException(400, "일시정지할 수 없는 상태입니다.")
        plan.status, sched.status = "paused", "paused"
    elif action == "resume":
        if plan.status != "paused":
            raise HTTPException(400, "일시정지 상태가 아닙니다.")
        plan.status, sched.status = "running", "active"
        sched.next_run_at = max(sched.next_run_at or utcnow(), utcnow())
    elif action == "cancel":
        if plan.status in ("completed", "cancelled"):
            raise HTTPException(400, "이미 종료된 검사입니다.")
        order_svc.stop_plan(db, plan, "cancelled")
        plan.order.status = "cancelled"
    elif action == "run-now":
        if plan.status not in ("scheduled", "running"):
            raise HTTPException(400, "기기가 배정된 진행 중 검사만 즉시 실행할 수 있습니다.")
        n = order_svc.create_jobs_for_run(db, plan, "M" + utcnow().strftime("%Y%m%dT%H%M%S"), "manual")
        if plan.status == "scheduled":
            plan.status, plan.order.status = "running", "running"
        db.commit()
        for aid in db.scalars(select(TestJob.agent_id).where(TestJob.plan_id == pid, TestJob.status == "queued").distinct()):
            hub.wake(aid)
        audit(db, user.id, "plan.run_now", "plan", pid, {"jobs": n}, client_ip(request))
        db.commit()
        return {"ok": True, "jobs_created": n}
    elif action == "allocate":
        ok = order_svc.allocate_plan(db, plan)
        db.commit()
        return {"ok": ok}
    else:
        raise HTTPException(400, "지원하지 않는 동작입니다.")
    audit(db, user.id, f"plan.{action}", "plan", pid, ip=client_ip(request))
    db.commit()
    return admin_plan_view(db, plan)


@router.get("/plans/{pid}")
def plan_detail(pid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    from .customer import plan_detail as customer_plan_detail
    plan = db.get(TestPlan, pid)
    if not plan:
        raise HTTPException(404, "검사 계획을 찾을 수 없습니다.")
    return {**customer_plan_detail(pid, db.get(Customer, plan.customer_id), db), **admin_plan_view(db, plan)}


# ---------------- 시나리오(공용) ----------------
class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    steps: list[dict]


@router.get("/scenarios")
def scenarios(db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    return [{**scenario_view(s), "customer_id": s.customer_id}
            for s in db.scalars(select(TestScenario).where(TestScenario.is_active.is_(True)).order_by(TestScenario.id.desc()).limit(500))]


@router.post("/scenarios")
def create_scenario(body: ScenarioIn, db: Session = Depends(get_db), user: User = Depends(require_perm("tests"))):
    s = TestScenario(customer_id=None, name=body.name, steps=validate_steps(body.steps), created_by=user.id)
    db.add(s)
    db.commit()
    return scenario_view(s)


@router.put("/scenarios/{sid}")
def update_scenario(sid: int, body: ScenarioIn, db: Session = Depends(get_db), user: User = Depends(require_perm("tests"))):
    old = db.get(TestScenario, sid)
    if not old:
        raise HTTPException(404, "시나리오를 찾을 수 없습니다.")
    old.is_active = False
    new = TestScenario(customer_id=old.customer_id, app_id=old.app_id, name=body.name, steps=validate_steps(body.steps),
                       version=old.version + 1, root_id=old.root_id or old.id, created_by=user.id)
    db.add(new)
    db.commit()
    return scenario_view(new)


@router.delete("/scenarios/{sid}")
def delete_scenario(sid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    s = db.get(TestScenario, sid)
    if s:
        s.is_active = False
        db.commit()
    return {"ok": True}


# ---------------- 결과 / 오류 / 스크린샷 / 보고서 ----------------
@router.get("/results")
def results(status: str = "", mock: bool | None = None, plan_id: int | None = None, db: Session = Depends(get_db),
            _: User = Depends(require_perm("tests"))):
    stmt = select(TestResult, TestPlan).join(TestPlan, TestPlan.id == TestResult.plan_id)
    if status:
        stmt = stmt.where(TestResult.status == status)
    if mock is not None:
        stmt = stmt.where(TestResult.is_mock.is_(mock))
    if plan_id:
        stmt = stmt.where(TestResult.plan_id == plan_id)
    rows = db.execute(stmt.order_by(TestResult.id.desc()).limit(500)).unique().all()
    return [{"id": r.id, "plan_id": r.plan_id, "app": p.app.name, "device": r.device.name or r.device.serial,
             "model": r.device.model, "android": r.device.android_version, "status": r.status, "steps": r.steps,
             "summary": r.summary, "duration_ms": r.duration_ms, "crash_count": r.crash_count, "anr_count": r.anr_count,
             "is_mock": r.is_mock, "created_at": r.created_at} for r, p in rows]


@router.get("/live")
def live(db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    """실시간 검사 현황."""
    running = db.scalars(select(TestJob).where(TestJob.status.in_(["leased", "running"])).order_by(TestJob.started_at)).unique().all()
    queued = db.scalar(select(func.count()).select_from(TestJob).where(TestJob.status == "queued")) or 0
    hour = utcnow() - timedelta(hours=1)
    recent = dict(db.execute(select(TestResult.status, func.count()).where(TestResult.created_at >= hour).group_by(TestResult.status)).all())
    upcoming = db.execute(select(TestSchedule, TestPlan).join(TestPlan, TestPlan.id == TestSchedule.plan_id)
                          .where(TestSchedule.status == "active", TestSchedule.next_run_at.isnot(None))
                          .order_by(TestSchedule.next_run_at).limit(20)).all()
    return {"running": [job_view(j) for j in running], "queued": queued, "last_hour": recent,
            "upcoming": [{"plan_id": p.id, "app": p.app.name, "next_run_at": s.next_run_at, "devices": p.device_count,
                          "status": p.status} for s, p in upcoming]}


@router.get("/crashes")
def crashes(mock: bool | None = None, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    stmt = select(CrashLog, TestPlan).join(TestPlan, TestPlan.id == CrashLog.plan_id)
    if mock is not None:
        stmt = stmt.where(CrashLog.is_mock.is_(mock))
    rows = db.execute(stmt.order_by(CrashLog.id.desc()).limit(500)).all()
    return [{"id": c.id, "plan_id": c.plan_id, "app": p.app.name, "kind": c.kind, "signature": c.signature, "title": c.title,
             "detail": c.detail, "severity": c.severity, "category": c.category, "analysis": c.analysis,
             "analysis_source": c.analysis_source, "device_id": c.device_id, "is_mock": c.is_mock, "created_at": c.created_at}
            for c, p in rows]


@router.post("/crashes/{cid}/analyze")
def analyze_crash(cid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    """AI 추정 분석 재실행. AI 미설정 시 규칙 기반 분석만 갱신한다."""
    c = db.get(CrashLog, cid)
    if not c:
        raise HTTPException(404, "오류 로그를 찾을 수 없습니다.")
    rule = analysis.analyze_rule(c.kind, c.title, c.detail)
    ai = analysis.analyze_ai(db, c.kind, c.title, c.detail)
    c.analysis = {"rule": rule, "ai": ai}
    c.severity, c.category = rule["severity"], rule["category"]
    c.analysis_source = "ai" if ai and not ai.get("error") else "rule"
    db.commit()
    return {"analysis": c.analysis, "ai_configured": analysis.ai_configured(db)}


@router.get("/screenshots")
def screenshots(plan_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    stmt = select(Screenshot)
    if plan_id:
        stmt = stmt.where(Screenshot.plan_id == plan_id)
    return [{"id": s.id, "plan_id": s.plan_id, "device_id": s.device_id, "label": s.label, "is_mock": s.is_mock,
             "created_at": s.created_at, "url": file_url("screenshot", s.id)}
            for s in db.scalars(stmt.order_by(Screenshot.id.desc()).limit(200))]


@router.get("/reports")
def reports(db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    rows = db.execute(select(Report, TestPlan).join(TestPlan, TestPlan.id == Report.plan_id).order_by(Report.id.desc()).limit(300)).all()
    return {"kinds": KINDS, "items": [report_view(r, p) for r, p in rows]}


class ReportIn(BaseModel):
    plan_id: int
    kind: str
    fmt: str = "pdf"


@router.post("/reports")
def make_report(body: ReportIn, db: Session = Depends(get_db), _: User = Depends(require_perm("tests"))):
    plan = db.get(TestPlan, body.plan_id)
    if not plan:
        raise HTTPException(404, "검사 계획을 찾을 수 없습니다.")
    try:
        rep = generate_report(db, plan, body.kind, body.fmt)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return report_view(rep, plan)
