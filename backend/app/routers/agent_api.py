"""PC 에이전트 전용 API. 관리자 인증과 분리된 에이전트 인증키(X-Agent-Token)를 사용한다."""
import asyncio
import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db, utcnow
from ..deps import agent_from_token, client_ip, current_agent, rate_limit
from ..hub import hub
from ..models import (Agent, AgentToken, AppFile, Device, DeviceCommand, DeviceHeartbeat, Screenshot, TestJob,
                      TestPlan)
from ..security import new_token, sha256_hex
from ..services import results as result_svc
from ..services import settings_store, storage
from ..services.audit import syslog
from ..services.scheduler import device_status

router = APIRouter(prefix="/api/agent", tags=["agent"])
PNG, JPG = b"\x89PNG", b"\xff\xd8"


def issue_agent_token(db: Session, agent: Agent) -> tuple[str, AgentToken]:
    plain, hashed = new_token(40)
    row = AgentToken(agent_id=agent.id, token_hash=hashed,
                     expires_at=utcnow() + timedelta(days=settings_store.get_int(db, "agent.token_days")))
    db.add(row)
    return plain, row


class EnrollIn(BaseModel):
    code: str
    hostname: str = ""
    os: str = ""
    version: str = ""


@router.post("/enroll", dependencies=[Depends(rate_limit(10, "enroll"))])
def enroll(body: EnrollIn, request: Request, db: Session = Depends(get_db)):
    """최초 등록: 관리자가 발급한 1회용 등록 코드를 인증키로 교환한다."""
    agent = db.scalar(select(Agent).where(Agent.enroll_code_hash == sha256_hex(body.code.strip())).with_for_update(of=Agent))
    if not agent or agent.status == "revoked" or not agent.enroll_expires_at or agent.enroll_expires_at < utcnow():
        raise HTTPException(401, "등록 코드가 유효하지 않거나 만료되었습니다.")
    agent.enroll_code_hash, agent.enroll_expires_at = None, None
    agent.hostname, agent.os, agent.version = body.hostname[:160], body.os[:80], body.version[:30]
    agent.status, agent.last_seen_at, agent.ip = "online", utcnow(), client_ip(request)
    token, row = issue_agent_token(db, agent)
    syslog(db, "info", "agent", f"에이전트 등록: {agent.name} ({agent.uid})")
    db.commit()
    return {"agent_id": agent.uid, "name": agent.name, "kind": agent.kind, "token": token, "expires_at": row.expires_at}


@router.post("/token/rotate")
def rotate(request: Request, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    old_hash = sha256_hex(request.headers.get("x-agent-token", ""))
    token, row = issue_agent_token(db, agent)
    db.execute(update(AgentToken).where(AgentToken.token_hash == old_hash).values(revoked_at=utcnow()))
    db.commit()
    return {"token": token, "expires_at": row.expires_at}


class DeviceIn(BaseModel):
    serial: str
    state: str = "device"
    manufacturer: str = ""
    model: str = ""
    android_version: str = ""
    sdk: int = 0
    cpu: str = ""
    ram_mb: int = 0
    storage_total_mb: int = 0
    storage_free_mb: int = 0
    battery: int = 0
    temperature: float = 0
    resolution: str = ""
    network: str = ""
    installed: dict[str, str] = {}


class HeartbeatIn(BaseModel):
    version: str = ""
    hostname: str = ""
    devices: list[DeviceIn] = []
    running_jobs: list[int] = []


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, request: Request, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    now = utcnow()
    agent.status, agent.last_seen_at, agent.ip = "online", now, client_ip(request)
    if body.version:
        agent.version = body.version[:30]
    known = {d.serial: d for d in db.scalars(select(Device).where(Device.agent_id == agent.id))}
    seen = set()
    for item in body.devices[:2000]:
        serial = item.serial.strip()[:120]
        if not serial:
            continue
        seen.add(serial)
        dev = known.get(serial)
        if dev is None:
            dev = Device(agent_id=agent.id, serial=serial, is_mock=agent.kind == "mock",
                         name=f"{'MOCK-' if agent.kind == 'mock' else ''}{item.model or serial}"[:120])
            db.add(dev)
            known[serial] = dev
        sample = dev.last_seen_at is None or (now - dev.last_seen_at) > timedelta(minutes=5) or \
            (now.minute // 5) != (dev.last_seen_at.minute // 5)
        data = item.model_dump()
        for f in ("manufacturer", "model", "android_version", "sdk", "cpu", "ram_mb", "storage_total_mb",
                  "storage_free_mb", "battery", "temperature", "resolution", "network"):
            if data[f] not in ("", 0, 0.0) or f in ("battery", "temperature", "storage_free_mb"):
                setattr(dev, f, data[f])
        dev.conn_state = item.state if item.state in ("device", "unauthorized", "offline") else "offline"
        dev.installed_apps = {k[:200]: str(v)[:60] for k, v in list(item.installed.items())[:50]}
        dev.last_seen_at = now
        db.flush()
        dev.status = device_status(db, dev)
        if sample:
            db.add(DeviceHeartbeat(device_id=dev.id, battery=dev.battery, temperature=dev.temperature,
                                   storage_free_mb=dev.storage_free_mb, status=dev.status))
    for serial, dev in known.items():
        if serial not in seen and dev.conn_state != "offline":
            dev.conn_state = "offline"
            dev.status = device_status(db, dev)
    # 서버에서 취소/회수된 작업을 에이전트에 알려 중단시킨다
    cancel = []
    if body.running_jobs:
        live = set(db.scalars(select(TestJob.id).where(TestJob.id.in_(body.running_jobs), TestJob.agent_id == agent.id,
                                                       TestJob.status.in_(["leased", "running"]))))
        cancel = [j for j in body.running_jobs if j not in live]
    commands = db.scalars(select(DeviceCommand).where(DeviceCommand.agent_id == agent.id, DeviceCommand.status == "queued")
                          .order_by(DeviceCommand.id).limit(50).with_for_update(of=DeviceCommand, skip_locked=True)).all()
    out = []
    for c in commands:
        c.status = "sent"
        dev = db.get(Device, c.device_id)
        out.append({"id": c.id, "type": c.type, "serial": dev.serial, "params": c.params or {}})
    db.commit()
    return {"server_time": now, "commands": out, "cancel_jobs": cancel,
            "latest_version": settings_store.get(db, "agent.latest_version")}


class ClaimIn(BaseModel):
    limit: int = 5


@router.post("/jobs/claim")
def claim(body: ClaimIn, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    """작업 수신. 행 잠금(SKIP LOCKED) + 임대 시간 + 기기당 1작업 유일 인덱스로 중복 실행을 방지한다."""
    now = utcnow()
    running = db.scalar(select(func.count()).select_from(TestJob).where(
        TestJob.agent_id == agent.id, TestJob.status.in_(["leased", "running"]))) or 0
    room = min(max(1, body.limit), settings_store.get_int(db, "limits.max_jobs_per_agent") - running)
    if room <= 0:
        return {"jobs": []}
    busy = select(TestJob.device_id).where(TestJob.status.in_(["leased", "running"]))
    rows = db.scalars(
        select(TestJob).join(TestPlan, TestPlan.id == TestJob.plan_id).join(Device, Device.id == TestJob.device_id)
        .where(TestJob.agent_id == agent.id, TestJob.status == "queued", TestJob.next_attempt_at <= now,
               TestPlan.status.in_(["scheduled", "running"]), Device.conn_state == "device", Device.enabled.is_(True),
               Device.maintenance.is_(False), Device.status.notin_(["overheat", "low_storage"]),
               TestJob.device_id.notin_(busy))
        .order_by(TestJob.priority.desc(), TestJob.id).limit(room * 4)
        .with_for_update(of=TestJob, skip_locked=True)).unique().all()
    out, used = [], set()
    for job in rows:
        if job.device_id in used or len(out) >= room:
            continue
        sp = db.begin_nested()
        try:
            job.status, job.attempts, job.lease_token = "leased", job.attempts + 1, secrets.token_hex(16)
            job.lease_expires_at, job.started_at, job.progress = now + timedelta(seconds=job.timeout_sec), now, 0
            db.flush()
            sp.commit()
        except IntegrityError:
            sp.rollback()
            db.refresh(job)
            continue
        used.add(job.device_id)
        job.device.status = "testing"
        out.append({"id": job.id, "lease_token": job.lease_token, "serial": job.device.serial, "attempt": job.attempts,
                    "timeout_sec": job.timeout_sec, "is_mock": job.is_mock, "payload": job.payload})
    db.commit()
    return {"jobs": out}


def leased_job(db: Session, agent: Agent, job_id: int, lease_token: str, allow_done: bool = False) -> TestJob:
    job = db.scalar(select(TestJob).where(TestJob.id == job_id, TestJob.agent_id == agent.id).with_for_update(of=TestJob))
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    if allow_done and job.status == "succeeded":
        return job
    if job.status not in ("leased", "running") or job.lease_token != lease_token:
        raise HTTPException(409, "임대가 만료되었거나 취소된 작업입니다.")
    return job


class ProgressIn(BaseModel):
    lease_token: str
    progress: int = 0


@router.post("/jobs/{job_id}/progress")
def progress(job_id: int, body: ProgressIn, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    job = leased_job(db, agent, job_id, body.lease_token)
    job.status, job.progress = "running", max(0, min(99, body.progress))
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/result")
def result(job_id: int, body: dict, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    job = leased_job(db, agent, job_id, str(body.get("lease_token", "")), allow_done=True)
    res = result_svc.ingest(db, job, body)
    job.device.status = device_status(db, job.device, busy=False)
    db.commit()
    return {"ok": True, "result_id": res.id}


class FailIn(BaseModel):
    lease_token: str
    error: str
    retryable: bool = True


@router.post("/jobs/{job_id}/fail")
def fail(job_id: int, body: FailIn, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    """검사를 수행하지 못한 경우(설치 불가, ADB 오류 등). 재시도 가능하면 지수 백오프로 다시 대기열에 넣는다."""
    job = leased_job(db, agent, job_id, body.lease_token)
    if not body.retryable:
        job.attempts = job.max_attempts
    result_svc.retry_or_fail(db, job, body.error)
    job.device.status = device_status(db, job.device, busy=False)
    db.commit()
    return {"ok": True, "status": job.status}


async def _save_image(file: UploadFile, sha256: str) -> tuple[str, int, str]:
    rel, size, digest = await storage.save_upload(file, "screenshots", ".png", 15 * 1024 * 1024)
    with open(storage.abspath(rel), "rb") as fh:
        head = fh.read(4)
    if digest != sha256.lower() or not (head.startswith(PNG) or head.startswith(JPG)):
        storage.remove(rel)
        raise HTTPException(422, "파일 무결성 검증에 실패했습니다. 다시 전송해 주세요.")
    return rel, size, digest


@router.post("/jobs/{job_id}/screenshot")
async def job_screenshot(job_id: int, lease_token: str = Form(...), label: str = Form(""), sha256: str = Form(...),
                         file: UploadFile = File(...), agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    job = leased_job(db, agent, job_id, lease_token, allow_done=True)
    dup = db.scalar(select(Screenshot).where(Screenshot.job_id == job.id, Screenshot.sha256 == sha256.lower(),
                                           Screenshot.label == label[:160]))
    if dup:
        return {"ok": True, "id": dup.id, "duplicate": True}
    rel, size, digest = await _save_image(file, sha256)
    plan = db.get(TestPlan, job.plan_id)
    shot = Screenshot(job_id=job.id, device_id=job.device_id, customer_id=plan.customer_id, plan_id=plan.id,
                      label=label[:160], path=rel, sha256=digest, size=size, is_mock=job.is_mock)
    db.add(shot)
    db.commit()
    return {"ok": True, "id": shot.id}


@router.get("/files/{file_id}")
def download_file(file_id: int, agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    """APK 다운로드. 이 에이전트에 배정된 작업/명령이 참조하는 파일만 허용한다."""
    row = db.get(AppFile, file_id)
    if not row or row.kind not in ("apk", "transfer") or row.status != "clean":
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    jobs = db.scalars(select(TestJob).where(TestJob.agent_id == agent.id, TestJob.status.in_(["leased", "running"]))).all()
    allowed = any(((j.payload or {}).get("apk") or {}).get("file_id") == file_id for j in jobs)
    if not allowed:
        cmds = db.scalars(select(DeviceCommand).where(DeviceCommand.agent_id == agent.id, DeviceCommand.status == "sent",
                                                      DeviceCommand.type.in_(["install_apk", "push_file"]))).all()
        allowed = any((c.params or {}).get("file_id") == file_id for c in cmds)
    if not allowed:
        raise HTTPException(403, "이 파일에 대한 권한이 없습니다.")
    return FileResponse(storage.abspath(row.path), media_type="application/octet-stream",
                        headers={"X-Sha256": row.sha256})


@router.post("/commands/{cmd_id}/result")
async def command_result(cmd_id: int, status: str = Form(...), message: str = Form(""), sha256: str = Form(""),
                         file: UploadFile | None = File(None), agent: Agent = Depends(current_agent),
                         db: Session = Depends(get_db)):
    cmd = db.scalar(select(DeviceCommand).where(DeviceCommand.id == cmd_id, DeviceCommand.agent_id == agent.id).with_for_update(of=DeviceCommand))
    if not cmd:
        raise HTTPException(404, "명령을 찾을 수 없습니다.")
    if cmd.status in ("done", "failed"):
        return {"ok": True, "duplicate": True}
    result = {"message": message[:4000]}
    if file is not None and file.filename:
        rel, size, digest = await _save_image(file, sha256)
        dev = db.get(Device, cmd.device_id)
        shot = Screenshot(command_id=cmd.id, device_id=cmd.device_id, label="원격 제어 스크린샷", path=rel, sha256=digest,
                          size=size, is_mock=dev.is_mock)
        db.add(shot)
        db.flush()
        result["screenshot_id"] = shot.id
    cmd.status, cmd.result, cmd.finished_at = ("done" if status == "done" else "failed"), result, utcnow()
    db.commit()
    return {"ok": True}


@router.websocket("/ws")
async def agent_ws(ws: WebSocket):
    """인증된 WebSocket. 첫 메시지로 인증키를 받는다(URL에 키를 노출하지 않음)."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10)
        with SessionLocal() as db:
            agent = agent_from_token(db, str(first.get("token", "")))
            agent_id = agent.id
    except (asyncio.TimeoutError, HTTPException, WebSocketDisconnect, ValueError):
        await ws.close(code=4401)
        return
    queue = hub.register(agent_id)
    await ws.send_json({"type": "hello"})

    async def reader():
        while True:
            await ws.receive_text()  # ping 등은 무시, 끊김 감지용

    task = asyncio.create_task(reader())
    try:
        while not task.done():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=25)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        task.cancel()
        hub.unregister(agent_id, queue)
