"""고객용 API. 모든 조회는 customer_id로 격리한다."""
import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..deps import current_customer, current_user
from ..models import (App, AppFile, AppVersion, CrashLog, Customer, Device, DeviceAssignment, Notification, Order,
                      Payment, PerformanceMetric, Product, Report, Screenshot, SupportTicket, TestJob, TestPlan,
                      TestResult, TestScenario, TestSchedule, TesterInvite, TicketMessage, User)
from ..security import check_path_signature, decrypt, encrypt, sign_path
from ..services import orders as order_svc
from ..services import storage
from ..services.reports import KINDS, generate_report

router = APIRouter(prefix="/api", tags=["customer"])
PACKAGE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
SCENARIO_ACTIONS = {"launch", "find", "tap", "input", "scroll", "back", "home", "wait", "screenshot",
                    "assert_exists", "assert_text", "assert_no_error", "stop"}


def own_app(db: Session, customer: Customer, app_id: int) -> App:
    app = db.get(App, app_id)
    if not app or app.customer_id != customer.id or app.deleted_at:
        raise HTTPException(404, "앱을 찾을 수 없습니다.")
    return app


def own_plan(db: Session, customer: Customer, plan_id: int) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if not plan or plan.customer_id != customer.id:
        raise HTTPException(404, "검사 정보를 찾을 수 없습니다.")
    return plan


def file_url(kind: str, obj_id: int) -> str:
    path = f"/api/files/{kind}/{obj_id}"
    return f"{path}?{sign_path(path)}"


def app_view(app: App) -> dict:
    return {"id": app.id, "name": app.name, "package_name": app.package_name, "play_url": app.play_url,
            "closed_test_url": app.closed_test_url, "google_group": app.google_group, "description": app.description,
            "request_notes": app.request_notes, "languages": app.languages or [],
            "has_test_login": bool(app.test_login_enc), "ownership_confirmed": app.ownership_confirmed,
            "closed_test_started_on": app.closed_test_started_on, "improvements": app.improvements,
            "icon_url": file_url("icon", app.icon_file_id) if app.icon_file_id else None, "created_at": app.created_at,
            "versions": [version_view(v) for v in app.versions]}


def version_view(v: AppVersion) -> dict:
    f = v.file
    return {"id": v.id, "version_name": v.version_name, "version_code": v.version_code, "notes": v.notes,
            "created_at": v.created_at,
            "file": {"filename": f.filename, "size": f.size, "sha256": f.sha256, "status": f.status,
                     "quarantine_reason": f.quarantine_reason} if f else None}


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    package_name: str
    play_url: str = ""
    closed_test_url: str = ""
    google_group: str = ""
    description: str = ""
    request_notes: str = ""
    languages: list[str] = []
    test_login_id: str | None = None
    test_login_password: str | None = None
    ownership_confirmed: bool = False
    closed_test_started_on: str = ""
    improvements: str = ""


def _apply_app(app: App, body: AppIn):
    for url in (body.play_url, body.closed_test_url):
        if url and not url.startswith("https://"):
            raise HTTPException(400, "주소는 https:// 로 시작해야 합니다.")
    for f in ("name", "play_url", "closed_test_url", "google_group", "description", "request_notes",
              "closed_test_started_on", "improvements"):
        setattr(app, f, getattr(body, f).strip())
    app.languages = body.languages[:20]
    if body.test_login_id is not None or body.test_login_password is not None:
        creds = {"login_id": body.test_login_id or "", "login_password": body.test_login_password or ""}
        app.test_login_enc = encrypt(json.dumps(creds)) if any(creds.values()) else ""
    if body.ownership_confirmed and not app.ownership_confirmed:
        app.ownership_confirmed, app.ownership_confirmed_at = True, utcnow()


@router.get("/apps")
def list_apps(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    apps = db.scalars(select(App).where(App.customer_id == customer.id, App.deleted_at.is_(None)).order_by(App.id.desc()))
    return [app_view(a) for a in apps]


@router.post("/apps")
def create_app(body: AppIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    pkg = body.package_name.strip()
    if not PACKAGE_RE.match(pkg) or len(pkg) > 255:
        raise HTTPException(400, "패키지명 형식이 올바르지 않습니다. 예: com.example.app")
    if not body.ownership_confirmed:
        raise HTTPException(400, "검사 권한을 보유한 앱만 등록할 수 있습니다. 권한 확인에 동의해 주세요.")
    if db.scalar(select(App.id).where(App.customer_id == customer.id, App.package_name == pkg)):
        raise HTTPException(409, "이미 등록된 패키지명입니다.")
    app = App(customer_id=customer.id, package_name=pkg, name=body.name)
    _apply_app(app, body)
    db.add(app)
    db.commit()
    db.refresh(app)
    return app_view(app)


@router.get("/apps/{app_id}")
def get_app(app_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    return app_view(own_app(db, customer, app_id))


@router.put("/apps/{app_id}")
def update_app(app_id: int, body: AppIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    app = own_app(db, customer, app_id)
    if body.package_name.strip() != app.package_name:
        raise HTTPException(400, "패키지명은 변경할 수 없습니다.")
    _apply_app(app, body)
    db.commit()
    db.refresh(app)
    return app_view(app)


@router.delete("/apps/{app_id}")
def delete_app(app_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    app = own_app(db, customer, app_id)
    if db.scalar(select(TestPlan.id).where(TestPlan.app_id == app.id,
                                           TestPlan.status.in_(["waiting_devices", "scheduled", "running", "paused"])).limit(1)):
        raise HTTPException(400, "진행 중인 검사가 있는 앱은 삭제할 수 없습니다.")
    app.deleted_at = utcnow()
    app.package_name = f"{app.package_name}#deleted{app.id}"
    app.test_login_enc = ""
    db.commit()
    return {"ok": True}


@router.post("/apps/{app_id}/icon")
async def upload_icon(app_id: int, file: UploadFile = File(...), customer: Customer = Depends(current_customer),
                      db: Session = Depends(get_db)):
    app = own_app(db, customer, app_id)
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "아이콘은 PNG, JPG, WEBP 형식만 가능합니다.")
    rel, size, sha = await storage.save_upload(file, "icons", ext, 2 * 1024 * 1024)
    with open(storage.abspath(rel), "rb") as fh:
        head = fh.read(12)
    if not (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head[8:12] == b"WEBP"):
        storage.remove(rel)
        raise HTTPException(400, "이미지 파일이 아닙니다.")
    row = AppFile(app_id=app.id, customer_id=customer.id, kind="icon", filename=file.filename or "icon", path=rel,
                  size=size, sha256=sha)
    db.add(row)
    db.flush()
    app.icon_file_id = row.id
    db.commit()
    return {"icon_url": file_url("icon", row.id)}


@router.post("/apps/{app_id}/versions")
async def add_version(app_id: int, version_name: str = Form(...), version_code: int = Form(...), notes: str = Form(""),
                      file: UploadFile | None = File(None), customer: Customer = Depends(current_customer),
                      db: Session = Depends(get_db)):
    """앱 버전 등록(+APK 업로드). 형식·크기·해시·중복·패키지명 일치를 검증하고 이상 파일은 격리한다."""
    app = own_app(db, customer, app_id)
    if version_code <= 0 or not version_name.strip():
        raise HTTPException(400, "버전 정보가 올바르지 않습니다.")
    if db.scalar(select(AppVersion.id).where(AppVersion.app_id == app.id, AppVersion.version_code == version_code)):
        raise HTTPException(409, "이미 등록된 버전 코드입니다.")
    file_row, warning = None, ""
    if file is not None and file.filename:
        if not file.filename.lower().endswith(".apk"):
            raise HTTPException(400, "APK 파일만 업로드할 수 있습니다.")
        rel, size, sha = await storage.save_upload(file, "apks", ".apk", settings.MAX_APK_MB * 1024 * 1024)
        dup = db.scalar(select(AppFile).where(AppFile.sha256 == sha, AppFile.app_id == app.id, AppFile.kind == "apk",
                                              AppFile.status == "clean"))
        if dup:
            storage.remove(rel)
            raise HTTPException(409, "동일한 APK 파일이 이미 등록되어 있습니다.")
        info = storage.inspect_apk(storage.abspath(rel))
        status, reason = "clean", ""
        if not info["ok"]:
            status, reason = "quarantined", info["reason"]
        elif info["manifest"].get("package") and info["manifest"]["package"] != app.package_name:
            status, reason = "quarantined", f"APK 패키지명({info['manifest']['package']})이 등록된 패키지명과 다릅니다."
        if status == "quarantined":
            rel = storage.move_to_quarantine(rel)
        file_row = AppFile(app_id=app.id, customer_id=customer.id, kind="apk", filename=file.filename[:255], path=rel,
                           size=size, sha256=sha, status=status, quarantine_reason=reason)
        db.add(file_row)
        db.flush()
        if status == "quarantined":
            db.commit()
            raise HTTPException(422, f"파일이 격리되었습니다: {reason}")
        m = info["manifest"]
        if m.get("version_code") and m["version_code"] != version_code:
            warning = f"APK의 버전 코드({m['version_code']})와 입력값이 다릅니다. APK 기준으로 저장했습니다."
            version_code = m["version_code"]
            if db.scalar(select(AppVersion.id).where(AppVersion.app_id == app.id, AppVersion.version_code == version_code)):
                raise HTTPException(409, "APK의 버전 코드가 이미 등록되어 있습니다.")
    version = AppVersion(app_id=app.id, version_name=version_name.strip()[:60], version_code=version_code,
                         file_id=file_row.id if file_row else None, notes=notes)
    db.add(version)
    db.commit()
    db.refresh(version)
    return {**version_view(version), "warning": warning}


# ---------------- 시나리오 ----------------
def validate_steps(steps) -> list[dict]:
    if not isinstance(steps, list) or not steps or len(steps) > 200:
        raise HTTPException(400, "시나리오 단계는 1~200개여야 합니다.")
    clean = []
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or s.get("action") not in SCENARIO_ACTIONS:
            raise HTTPException(400, f"{i}번째 단계의 동작이 올바르지 않습니다.")
        sel = s.get("selector") or {}
        if s["action"] in ("find", "tap", "input", "assert_exists") and not any(sel.get(k) for k in ("resource_id", "text", "content_desc", "class_name")) \
                and not (s["action"] == "tap" and s.get("x") is not None):
            raise HTTPException(400, f"{i}번째 단계에 UI 요소 식별자(resource_id/text/content_desc)가 필요합니다.")
        clean.append({"action": s["action"], "name": str(s.get("name", ""))[:120],
                      "selector": {k: str(v)[:200] for k, v in sel.items() if k in ("resource_id", "text", "content_desc", "class_name") and v},
                      "text": str(s.get("text", ""))[:500], "expected": str(s.get("expected", ""))[:300],
                      "seconds": min(60, max(0, float(s.get("seconds") or 0))), "direction": str(s.get("direction", "down"))[:10],
                      "x": s.get("x"), "y": s.get("y"), "timeout": min(60, max(1, float(s.get("timeout") or 10)))})
    return clean


def scenario_view(s: TestScenario) -> dict:
    return {"id": s.id, "name": s.name, "version": s.version, "root_id": s.root_id or s.id, "app_id": s.app_id,
            "steps": s.steps, "is_active": s.is_active, "is_global": s.customer_id is None, "created_at": s.created_at}


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    app_id: int | None = None
    steps: list[dict]


@router.get("/scenarios")
def list_scenarios(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(TestScenario).where(TestScenario.is_active.is_(True),
                                                 (TestScenario.customer_id == customer.id) | (TestScenario.customer_id.is_(None)))
                      .order_by(TestScenario.id.desc()))
    return [scenario_view(s) for s in rows]


@router.post("/scenarios")
def create_scenario(body: ScenarioIn, user: User = Depends(current_user), customer: Customer = Depends(current_customer),
                    db: Session = Depends(get_db)):
    if body.app_id:
        own_app(db, customer, body.app_id)
    s = TestScenario(customer_id=customer.id, app_id=body.app_id, name=body.name, steps=validate_steps(body.steps),
                     created_by=user.id)
    db.add(s)
    db.commit()
    return scenario_view(s)


@router.put("/scenarios/{sid}")
def update_scenario(sid: int, body: ScenarioIn, user: User = Depends(current_user),
                    customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    """수정 시 새 버전을 만든다(버전 관리). 이전 버전은 보존된다."""
    old = db.get(TestScenario, sid)
    if not old or old.customer_id != customer.id:
        raise HTTPException(404, "시나리오를 찾을 수 없습니다.")
    old.is_active = False
    new = TestScenario(customer_id=customer.id, app_id=body.app_id or old.app_id, name=body.name,
                       steps=validate_steps(body.steps), version=old.version + 1, root_id=old.root_id or old.id,
                       created_by=user.id)
    db.add(new)
    db.commit()
    return scenario_view(new)


@router.get("/scenarios/{sid}/versions")
def scenario_versions(sid: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    s = db.get(TestScenario, sid)
    if not s or s.customer_id not in (customer.id, None):
        raise HTTPException(404, "시나리오를 찾을 수 없습니다.")
    root = s.root_id or s.id
    rows = db.scalars(select(TestScenario).where((TestScenario.root_id == root) | (TestScenario.id == root))
                      .order_by(TestScenario.version.desc()))
    return [scenario_view(r) for r in rows]


@router.delete("/scenarios/{sid}")
def delete_scenario(sid: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    s = db.get(TestScenario, sid)
    if not s or s.customer_id != customer.id:
        raise HTTPException(404, "시나리오를 찾을 수 없습니다.")
    s.is_active = False
    db.commit()
    return {"ok": True}


# ---------------- 주문 ----------------
def order_view(db: Session, o: Order, detail: bool = False) -> dict:
    data = {"id": o.id, "order_no": o.order_no, "status": o.status, "amount": o.amount, "discount": o.discount,
            "final_amount": o.final_amount, "is_mock": o.is_mock, "created_at": o.created_at, "paid_at": o.paid_at,
            "completed_at": o.completed_at, "app": {"id": o.app.id, "name": o.app.name, "package_name": o.app.package_name},
            "version": f"{o.app_version.version_name} ({o.app_version.version_code})",
            "product": {"name": o.product_snapshot["name"], "device_count": o.product_snapshot["device_count"],
                        "duration_days": o.product_snapshot["duration_days"], "daily_runs": o.product_snapshot["daily_runs"]}}
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == o.id))
    if plan:
        data["plan"] = plan_brief(db, plan)
    if detail:
        pays = db.scalars(select(Payment).where(Payment.order_id == o.id).order_by(Payment.id))
        data["payments"] = [{"id": p.id, "provider": p.provider, "mode": p.mode, "method": p.method, "amount": p.amount,
                             "status": p.status, "refunded_amount": p.refunded_amount, "receipt_url": p.receipt_url,
                             "failure_message": p.failure_message, "approved_at": p.approved_at} for p in pays]
        data["request_notes"], data["desired_android"] = o.request_notes, o.desired_android
    return data


def plan_brief(db: Session, plan: TestPlan) -> dict:
    counts = dict(db.execute(select(TestResult.status, func.count()).where(TestResult.plan_id == plan.id)
                             .group_by(TestResult.status)).all())
    total = sum(counts.values())
    assigned = db.scalar(select(func.count()).select_from(DeviceAssignment).where(
        DeviceAssignment.plan_id == plan.id, DeviceAssignment.status == "active")) or 0
    connected = db.scalar(select(func.count()).select_from(DeviceAssignment).join(Device).where(
        DeviceAssignment.plan_id == plan.id, DeviceAssignment.status == "active", Device.conn_state == "device")) or 0
    now = utcnow()
    span = (plan.end_at - plan.start_at).total_seconds() or 1
    progress = 100 if plan.status == "completed" else max(0, min(100, int((now - plan.start_at).total_seconds() / span * 100))) \
        if plan.status in ("running", "paused") else 0
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == plan.id))
    return {"id": plan.id, "status": plan.status, "start_at": plan.start_at, "end_at": plan.end_at, "is_mock": plan.is_mock,
            "days_left": max(0, (plan.end_at - now).days) if plan.status in ("scheduled", "running", "paused") else 0,
            "device_count": plan.device_count, "assigned_devices": assigned, "connected_devices": connected,
            "total_runs": total, "passed": counts.get("passed", 0), "failed": counts.get("failed", 0),
            "error": counts.get("error", 0), "success_rate": round(counts.get("passed", 0) / total * 100, 1) if total else None,
            "progress": progress, "next_run_at": sched.next_run_at if sched else None,
            "last_run_at": sched.last_run_at if sched else None, "daily_runs": plan.daily_runs}


class OrderIn(BaseModel):
    app_id: int
    app_version_id: int
    product_id: int
    coupon_code: str = ""
    scenario_id: int | None = None
    desired_start: datetime | None = None
    desired_android: str = ""
    request_notes: str = ""


@router.post("/orders")
def create_order(body: OrderIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db),
                 idempotency_key: str | None = Header(None)):
    order = order_svc.create_order(db, customer, body.model_dump(), idempotency_key)
    db.commit()
    return order_view(db, order, True)


class QuoteIn(BaseModel):
    product_id: int
    coupon_code: str = ""


@router.post("/orders/quote")
def quote(body: QuoteIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    if not product or not product.is_active:
        raise HTTPException(404, "판매 중인 상품이 아닙니다.")
    _, discount = order_svc.coupon_discount(db, body.coupon_code, product)
    return {"amount": product.price, "discount": discount, "final_amount": product.price - discount}


@router.get("/orders")
def list_orders(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(Order).where(Order.customer_id == customer.id).order_by(Order.id.desc()).limit(200))
    return [order_view(db, o) for o in rows]


def own_order(db, customer, order_id) -> Order:
    o = db.get(Order, order_id)
    if not o or o.customer_id != customer.id:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    return o


@router.get("/orders/{order_id}")
def get_order(order_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    return order_view(db, own_order(db, customer, order_id), True)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    o = db.scalar(select(Order).where(Order.id == order_id, Order.customer_id == customer.id).with_for_update(of=Order))
    if not o:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    if o.status != "pending_payment":
        raise HTTPException(400, "결제 완료된 주문은 고객 문의를 통해 환불을 요청해 주세요.")
    o.status = "cancelled"
    db.commit()
    return {"ok": True}


# ---------------- 대시보드 / 검사 결과 ----------------
@router.get("/dashboard")
def dashboard(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    cid = customer.id
    statuses = dict(db.execute(select(Order.status, func.count()).where(Order.customer_id == cid).group_by(Order.status)).all())
    res = dict(db.execute(select(TestResult.status, func.count()).where(TestResult.customer_id == cid)
                          .group_by(TestResult.status)).all())
    crash, anr = db.execute(select(func.coalesce(func.sum(TestResult.crash_count), 0),
                                   func.coalesce(func.sum(TestResult.anr_count), 0)).where(TestResult.customer_id == cid)).one()
    day = func.date_trunc("day", TestResult.created_at)
    daily = db.execute(select(day, TestResult.status, func.count()).where(TestResult.customer_id == cid)
                       .group_by(day, TestResult.status).order_by(day.desc()).limit(90)).all()
    by_day = defaultdict(lambda: {"passed": 0, "failed": 0, "error": 0})
    for d, status, n in daily:
        by_day[d.strftime("%Y-%m-%d")][status] = n
    plans = db.scalars(select(TestPlan).where(TestPlan.customer_id == cid,
                                              TestPlan.status.in_(["waiting_devices", "scheduled", "running", "paused"]))
                       .order_by(TestPlan.id.desc())).all()
    total = sum(res.values())
    return {"apps": db.scalar(select(func.count()).select_from(App).where(App.customer_id == cid, App.deleted_at.is_(None))),
            "orders_active": sum(statuses.get(s, 0) for s in ("paid", "waiting_devices", "scheduled", "running")),
            "orders_completed": statuses.get("completed", 0), "orders_pending_payment": statuses.get("pending_payment", 0),
            "runs_total": total, "runs_passed": res.get("passed", 0), "runs_failed": res.get("failed", 0) + res.get("error", 0),
            "success_rate": round(res.get("passed", 0) / total * 100, 1) if total else None, "crash_count": crash, "anr_count": anr,
            "daily": [{"day": d, **v} for d, v in sorted(by_day.items())][-30:],
            "active_plans": [{**plan_brief(db, p), "app": p.app.name, "order_id": p.order_id, "order_no": p.order.order_no} for p in plans]}


@router.get("/plans/{plan_id}")
def plan_detail(plan_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    plan = own_plan(db, customer, plan_id)
    results = db.scalars(select(TestResult).where(TestResult.plan_id == plan.id)).all()
    daily, per_dev = defaultdict(Counter), defaultdict(Counter)
    for r in results:
        daily[r.created_at.strftime("%Y-%m-%d")][r.status] += 1
        per_dev[r.device_id][r.status] += 1
        per_dev[r.device_id]["crash"] += r.crash_count
        per_dev[r.device_id]["anr"] += r.anr_count
    assigns = db.scalars(select(DeviceAssignment).where(DeviceAssignment.plan_id == plan.id).order_by(DeviceAssignment.id)).all()
    devices = []
    for a in assigns:
        d = a.device
        job = db.scalar(select(TestJob).where(TestJob.plan_id == plan.id, TestJob.device_id == d.id,
                                              TestJob.status.in_(["leased", "running"])).limit(1))
        devices.append({"device_id": d.id, "name": d.name or f"기기 {d.id}", "model": f"{d.manufacturer} {d.model}".strip(),
                        "android": d.android_version, "resolution": d.resolution, "assignment": a.status,
                        "connected": d.conn_state == "device", "status": d.status, "running_job": bool(job),
                        "progress": job.progress if job else None,
                        **{k: per_dev[d.id][k] for k in ("passed", "failed", "error", "crash", "anr")}})
    metrics = db.execute(select(PerformanceMetric.metric, PerformanceMetric.unit, func.avg(PerformanceMetric.value),
                                func.max(PerformanceMetric.value), func.count())
                         .where(PerformanceMetric.plan_id == plan.id).group_by(PerformanceMetric.metric, PerformanceMetric.unit)).all()
    jobs = dict(db.execute(select(TestJob.status, func.count()).where(TestJob.plan_id == plan.id).group_by(TestJob.status)).all())
    return {**plan_brief(db, plan), "app": plan.app.name, "package_name": plan.app.package_name, "order_id": plan.order_id,
            "version": f"{plan.app_version.version_name} ({plan.app_version.version_code})", "checks": plan.checks,
            "daily": [{"day": d, **{k: c[k] for k in ("passed", "failed", "error")}} for d, c in sorted(daily.items())],
            "devices": devices, "jobs": jobs,
            "metrics": [{"metric": m, "unit": u, "avg": round(a, 2), "max": round(mx, 2), "count": n} for m, u, a, mx, n in metrics]}


@router.get("/plans/{plan_id}/results")
def plan_results(plan_id: int, device_id: int | None = None, status: str | None = None, limit: int = 100, offset: int = 0,
                 customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    plan = own_plan(db, customer, plan_id)
    stmt = select(TestResult).where(TestResult.plan_id == plan.id)
    if device_id:
        stmt = stmt.where(TestResult.device_id == device_id)
    if status:
        stmt = stmt.where(TestResult.status == status)
    rows = db.scalars(stmt.order_by(TestResult.id.desc()).limit(min(limit, 200)).offset(offset)).all()
    return [{"id": r.id, "status": r.status, "device": r.device.name or f"기기 {r.device_id}",
             "model": f"{r.device.manufacturer} {r.device.model}".strip(), "android": r.device.android_version,
             "started_at": r.started_at, "finished_at": r.finished_at, "duration_ms": r.duration_ms,
             "crash_count": r.crash_count, "anr_count": r.anr_count, "steps": r.steps, "summary": r.summary,
             "is_mock": r.is_mock} for r in rows]


@router.get("/plans/{plan_id}/crashes")
def plan_crashes(plan_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    plan = own_plan(db, customer, plan_id)
    rows = db.scalars(select(CrashLog).where(CrashLog.plan_id == plan.id).order_by(CrashLog.id.desc()).limit(500)).all()
    groups: dict[str, dict] = {}
    for c in rows:
        g = groups.setdefault(c.signature, {"signature": c.signature, "kind": c.kind, "title": c.title, "category": c.category,
                                            "severity": c.severity, "count": 0, "devices": set(), "first_seen": c.created_at,
                                            "last_seen": c.created_at, "detail": c.detail, "analysis": c.analysis,
                                            "confirmed": True})
        g["count"] += 1
        g["devices"].add(c.device_id)
        g["first_seen"] = min(g["first_seen"], c.created_at)
    return [{**g, "devices": len(g["devices"])} for g in groups.values()]


@router.get("/plans/{plan_id}/screenshots")
def plan_screenshots(plan_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    plan = own_plan(db, customer, plan_id)
    rows = db.scalars(select(Screenshot).where(Screenshot.plan_id == plan.id).order_by(Screenshot.id.desc()).limit(300)).all()
    return [{"id": s.id, "label": s.label, "device_id": s.device_id, "created_at": s.created_at,
             "url": file_url("screenshot", s.id)} for s in rows]


# ---------------- 보고서 ----------------
def report_view(r: Report, plan: TestPlan | None = None) -> dict:
    return {"id": r.id, "report_no": r.report_no, "kind": r.kind, "kind_name": KINDS.get(r.kind, r.kind), "fmt": r.fmt,
            "size": r.size, "is_mock": r.is_mock, "created_at": r.created_at, "plan_id": r.plan_id,
            "app": plan.app.name if plan else None}


@router.get("/reports")
def list_reports(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.execute(select(Report, TestPlan).join(TestPlan, TestPlan.id == Report.plan_id)
                      .where(Report.customer_id == customer.id).order_by(Report.id.desc()).limit(300)).all()
    return {"kinds": KINDS, "items": [report_view(r, p) for r, p in rows]}


class ReportIn(BaseModel):
    kind: str
    fmt: str = "pdf"


@router.post("/plans/{plan_id}/reports")
def make_report(plan_id: int, body: ReportIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    plan = own_plan(db, customer, plan_id)
    snap = plan.order.product_snapshot or {}
    if body.fmt == "xlsx" and not snap.get("excel_report"):
        raise HTTPException(403, "이 상품은 Excel 보고서를 제공하지 않습니다.")
    if body.fmt == "pdf" and not snap.get("pdf_report", True):
        raise HTTPException(403, "이 상품은 PDF 보고서를 제공하지 않습니다.")
    try:
        rep = generate_report(db, plan, body.kind, body.fmt)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return report_view(rep, plan)


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rep = db.get(Report, report_id)
    if not rep or not (user.role.is_staff or (user.customer and rep.customer_id == user.customer.id)):
        raise HTTPException(404, "보고서를 찾을 수 없습니다.")
    media = "application/pdf" if rep.fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(storage.abspath(rep.path), media_type=media, filename=f"{rep.report_no}.{rep.fmt}")


# ---------------- 서명 URL 파일 ----------------
@router.get("/files/{kind}/{obj_id}")
def signed_file(kind: str, obj_id: int, exp: int, sig: str, request: Request, db: Session = Depends(get_db)):
    if not check_path_signature(request.url.path, exp, sig):
        raise HTTPException(403, "만료되었거나 잘못된 링크입니다.")
    if kind == "screenshot":
        row = db.get(Screenshot, obj_id)
        path, media = (row.path, "image/png") if row else (None, None)
    elif kind == "icon":
        row = db.get(AppFile, obj_id)
        path, media = (row.path, None) if row and row.kind == "icon" else (None, None)
    else:
        path = None
    if not path:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    return FileResponse(storage.abspath(path), media_type=media, headers={"Cache-Control": "private, max-age=600"})


# ---------------- 고객 문의 ----------------
def ticket_view(t: SupportTicket, full: bool = False) -> dict:
    data = {"id": t.id, "subject": t.subject, "category": t.category, "status": t.status, "created_at": t.created_at,
            "updated_at": t.updated_at}
    if full:
        data["messages"] = [{"id": m.id, "is_staff": m.is_staff, "body": m.body, "created_at": m.created_at} for m in t.messages]
    return data


class TicketIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    category: str = "general"
    body: str = Field(min_length=1, max_length=10000)


@router.get("/tickets")
def list_tickets(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(SupportTicket).where(SupportTicket.customer_id == customer.id).order_by(SupportTicket.id.desc()))
    return [ticket_view(t) for t in rows]


@router.post("/tickets")
def create_ticket(body: TicketIn, user: User = Depends(current_user), customer: Customer = Depends(current_customer),
                  db: Session = Depends(get_db)):
    t = SupportTicket(customer_id=customer.id, subject=body.subject, category=body.category[:40])
    db.add(t)
    db.flush()
    db.add(TicketMessage(ticket_id=t.id, author_id=user.id, body=body.body))
    db.commit()
    db.refresh(t)
    return ticket_view(t, True)


def own_ticket(db, customer, tid) -> SupportTicket:
    t = db.get(SupportTicket, tid)
    if not t or t.customer_id != customer.id:
        raise HTTPException(404, "문의를 찾을 수 없습니다.")
    return t


@router.get("/tickets/{tid}")
def get_ticket(tid: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    return ticket_view(own_ticket(db, customer, tid), True)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


@router.post("/tickets/{tid}/messages")
def add_message(tid: int, body: MessageIn, user: User = Depends(current_user),
                customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    t = own_ticket(db, customer, tid)
    db.add(TicketMessage(ticket_id=t.id, author_id=user.id, body=body.body))
    t.status, t.updated_at = "open", utcnow()
    db.commit()
    db.refresh(t)
    return ticket_view(t, True)


# ---------------- 알림 ----------------
@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.channel == "web")
                      .order_by(Notification.id.desc()).limit(100)).all()
    return {"unread": sum(1 for r in rows if r.status == "unread"),
            "items": [{"id": r.id, "event": r.event, "title": r.title, "body": r.body, "link": r.link,
                       "read": r.status == "read", "created_at": r.created_at} for r in rows]}


@router.post("/notifications/read")
def read_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(Notification.__table__.update().where(Notification.user_id == user.id, Notification.channel == "web",
                                                     Notification.status == "unread").values(status="read"))
    db.commit()
    return {"ok": True}


# ---------------- Google Play 비공개 테스트 지원(실제 테스터 관리) ----------------
class TesterIn(BaseModel):
    emails: list[str]


class TesterPatch(BaseModel):
    status: str | None = None
    feedback: str | None = None


def tester_view(t: TesterInvite) -> dict:
    return {"id": t.id, "email": t.email, "status": t.status, "feedback": t.feedback, "invited_at": t.invited_at,
            "joined_at": t.joined_at}


@router.get("/apps/{app_id}/closed-test")
def closed_test(app_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    """실제 테스터 수 / 실기기 검사 수량 / 기기 Google 계정 확인 수를 서로 다른 항목으로 분리해 보여준다."""
    app = own_app(db, customer, app_id)
    testers = db.scalars(select(TesterInvite).where(TesterInvite.app_id == app.id).order_by(TesterInvite.id)).all()
    tested = db.scalar(select(func.count(func.distinct(TestResult.device_id))).join(TestPlan, TestPlan.id == TestResult.plan_id)
                       .where(TestPlan.app_id == app.id, TestResult.is_mock.is_(False))) or 0
    accounts = db.scalar(select(func.count(func.distinct(Device.id))).join(DeviceAssignment, DeviceAssignment.device_id == Device.id)
                         .join(TestPlan, TestPlan.id == DeviceAssignment.plan_id)
                         .where(TestPlan.app_id == app.id, Device.google_account_confirmed.is_(True), Device.is_mock.is_(False))) or 0
    days = None
    if app.closed_test_started_on:
        try:
            days = (utcnow().date() - datetime.strptime(app.closed_test_started_on, "%Y-%m-%d").date()).days
        except ValueError:
            days = None
    return {"app": app_view(app), "testers": [tester_view(t) for t in testers],
            "human_testers_invited": len(testers), "human_testers_joined": sum(1 for t in testers if t.status in ("joined", "confirmed")),
            "human_testers_confirmed": sum(1 for t in testers if t.status == "confirmed"),
            "real_devices_tested": tested, "device_google_accounts_confirmed": accounts, "days_since_start": days,
            "notice": "기기 자동 검사 기록은 인간 테스터 참여로 집계되지 않습니다. Google Play 테스트 요건은 Google 공식 문서를 "
                      "기준으로 직접 확인해야 하며, 본 서비스는 프로덕션 승인을 보장하지 않습니다."}


@router.post("/apps/{app_id}/testers")
def add_testers(app_id: int, body: TesterIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    app = own_app(db, customer, app_id)
    existing = {t.email for t in db.scalars(select(TesterInvite).where(TesterInvite.app_id == app.id))}
    added = 0
    for raw in body.emails[:500]:
        email = raw.strip().lower()
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) and email not in existing:
            db.add(TesterInvite(app_id=app.id, customer_id=customer.id, email=email))
            existing.add(email)
            added += 1
    db.commit()
    return {"added": added}


@router.patch("/apps/{app_id}/testers/{tid}")
def patch_tester(app_id: int, tid: int, body: TesterPatch, customer: Customer = Depends(current_customer),
                 db: Session = Depends(get_db)):
    own_app(db, customer, app_id)
    t = db.get(TesterInvite, tid)
    if not t or t.app_id != app_id:
        raise HTTPException(404, "테스터를 찾을 수 없습니다.")
    if body.status in ("invited", "joined", "confirmed"):
        t.status = body.status
        t.joined_at = t.joined_at or (utcnow() if body.status != "invited" else None)
    if body.feedback is not None:
        t.feedback = body.feedback[:5000]
    db.commit()
    return tester_view(t)


@router.delete("/apps/{app_id}/testers/{tid}")
def delete_tester(app_id: int, tid: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    own_app(db, customer, app_id)
    t = db.get(TesterInvite, tid)
    if t and t.app_id == app_id:
        db.delete(t)
        db.commit()
    return {"ok": True}


@router.get("/apps/{app_id}/testers.csv")
def export_testers(app_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    app = own_app(db, customer, app_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    for t in db.scalars(select(TesterInvite).where(TesterInvite.app_id == app.id).order_by(TesterInvite.id)):
        writer.writerow([t.email])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="testers-{app.id}.csv"'})


@router.get("/apps/{app_id}/production-notes")
def production_notes(app_id: int, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    """프로덕션 신청 참고자료(초안). 실제 기록만 요약하며 승인 보장 문구를 포함하지 않는다."""
    data = closed_test(app_id, customer, db)
    app = own_app(db, customer, app_id)
    res = dict(db.execute(select(TestResult.status, func.count()).join(TestPlan, TestPlan.id == TestResult.plan_id)
                          .where(TestPlan.app_id == app.id, TestResult.is_mock.is_(False)).group_by(TestResult.status)).all())
    feedback = [t.feedback for t in db.scalars(select(TesterInvite).where(TesterInvite.app_id == app.id)) if t.feedback]
    lines = [f"[{app.name}] 프로덕션 신청 참고자료 (초안)", "",
             f"1. 비공개 테스트 시작일: {app.closed_test_started_on or '미입력'} (경과 {data['days_since_start'] if data['days_since_start'] is not None else '-'}일)",
             f"2. 실제 테스터: 초대 {data['human_testers_invited']}명 / 참여 {data['human_testers_joined']}명 / 참여 확인 {data['human_testers_confirmed']}명",
             f"3. 실기기 자동화 품질검사(테스터 참여와 별개): 기기 {data['real_devices_tested']}대, 검사 {sum(res.values())}회 "
             f"(성공 {res.get('passed', 0)} / 실패 {res.get('failed', 0)} / 수행 불가 {res.get('error', 0)})",
             "4. 테스터 피드백:"] + [f"   - {f}" for f in feedback[:30]] + (["   (등록된 피드백 없음)"] if not feedback else []) + \
            ["5. 테스트 결과를 반영한 개선사항:", f"   {app.improvements or '(미입력)'}", "",
             "※ 본 자료는 작성 보조용 초안이며, 실제 신청 답변은 Google Play Console의 최신 안내에 맞춰 직접 작성해야 합니다."]
    return {"text": "\n".join(lines)}
