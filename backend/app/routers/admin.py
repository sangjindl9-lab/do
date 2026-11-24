"""관리자 통합 운영 API (/api/admin). 메뉴별 권한 검증 + 감사 로그."""
import gzip
import json
import os
import shutil
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import DateTime, Boolean, Integer, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Base, engine, get_db, utcnow
from ..deps import client_ip, has_perm, require_perm, require_staff
from ..models import (Agent, Announcement, App, AppFile, AuditLog, BackupHistory, Coupon, Customer, Device, Faq,
                      LegalDoc, LoginHistory, Notification, NotificationTemplate, Order, Payment, PaymentEvent,
                      Permission, Product, Refund, Role, SupportTicket, SystemLog, TestJob, TestPlan, TestResult,
                      TicketMessage, User)
from ..security import hash_password, password_problem
from ..services import analysis, notifications, settings_store, storage
from ..services import orders as order_svc
from ..services.audit import audit
from ..services.payment_providers import PaymentError, get_provider
from .auth import revoke_sessions, user_view
from .customer import app_view, order_view, ticket_view
from .payments import payment_view

router = APIRouter(prefix="/api/admin", tags=["admin"])
STARTED = time.time()


def row_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def coerce(model, key: str, value):
    col = model.__table__.columns[key]
    if value in ("", None) and (isinstance(col.type, (DateTime, Integer)) and col.nullable):
        return None
    if isinstance(col.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(col.type, Boolean):
        return bool(value)
    if isinstance(col.type, Integer) and value is not None:
        return int(value)
    return value


def register_crud(path: str, model, perm: str, fields: list[str], order=None, label: str = ""):
    """단순 관리 메뉴용 CRUD 4종을 실제 DB에 연결한다."""
    name = label or model.__tablename__

    def _list(db: Session = Depends(get_db), _: User = Depends(require_perm(perm))):
        return [row_dict(o) for o in db.scalars(select(model).order_by(*(order or [model.id.desc()])).limit(1000))]

    def _save(obj, body: dict):
        unknown = set(body) - set(fields)
        if unknown:
            raise HTTPException(400, f"허용되지 않는 항목: {', '.join(sorted(unknown))}")
        try:
            for k, v in body.items():
                setattr(obj, k, coerce(model, k, v))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"입력값 형식이 올바르지 않습니다: {exc}") from exc

    def _create(body: dict, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm(perm))):
        obj = model()
        _save(obj, body)
        db.add(obj)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(409, "중복되었거나 필수 항목이 누락되었습니다.") from exc
        audit(db, user.id, f"{name}.create", name, obj.id, body, client_ip(request))
        db.commit()
        return row_dict(obj)

    def _update(oid: int, body: dict, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm(perm))):
        obj = db.get(model, oid)
        if not obj:
            raise HTTPException(404, "대상을 찾을 수 없습니다.")
        _save(obj, body)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(409, "중복되었거나 필수 항목이 누락되었습니다.") from exc
        audit(db, user.id, f"{name}.update", name, oid, body, client_ip(request))
        db.commit()
        return row_dict(obj)

    def _delete(oid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm(perm))):
        obj = db.get(model, oid)
        if not obj:
            raise HTTPException(404, "대상을 찾을 수 없습니다.")
        db.delete(obj)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(409, "다른 데이터에서 사용 중이라 삭제할 수 없습니다. 비활성화를 이용해 주세요.") from exc
        audit(db, user.id, f"{name}.delete", name, oid, ip=client_ip(request))
        db.commit()
        return {"ok": True}

    router.add_api_route(path, _list, methods=["GET"])
    router.add_api_route(path, _create, methods=["POST"])
    router.add_api_route(path + "/{oid}", _update, methods=["PUT"])
    router.add_api_route(path + "/{oid}", _delete, methods=["DELETE"])


register_crud("/products", Product, "products",
              ["code", "name", "description", "description_en", "list_price", "discount_price", "price", "duration_days",
               "device_count", "daily_runs", "checks", "ai_analysis", "pdf_report", "excel_report", "priority",
               "coupon_allowed", "is_active", "is_quote", "sort"], order=[Product.sort, Product.id])
register_crud("/coupons", Coupon, "products", ["code", "kind", "value", "max_uses", "min_amount", "valid_from", "valid_to", "is_active"])
register_crud("/announcements", Announcement, "support", ["title", "body", "is_published", "pinned"])
register_crud("/faqs", Faq, "support", ["question", "answer", "locale", "sort", "is_published"], order=[Faq.sort, Faq.id])
register_crud("/notification-templates", NotificationTemplate, "system", ["event", "locale", "subject", "body"],
              order=[NotificationTemplate.event, NotificationTemplate.locale])


# ---------------- 통합 대시보드 ----------------
def revenue_rows(db: Session, unit: str, mock: bool, since: datetime | None = None):
    bucket = func.date_trunc(unit, Payment.approved_at)
    cond = [Payment.status.in_(["paid", "partial_refunded", "refunded"]),
            (Payment.mode == "mock") if mock else (Payment.mode != "mock")]
    if since:
        cond.append(Payment.approved_at >= since)
    return db.execute(select(bucket, func.count(), func.sum(Payment.amount), func.sum(Payment.refunded_amount))
                      .where(*cond).group_by(bucket).order_by(bucket.desc()).limit(400)).all()


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_perm("dashboard"))):
    now = utcnow()
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    dev = dict(db.execute(select(Device.status, func.count()).where(Device.is_mock.is_(False)).group_by(Device.status)).all())
    mock_dev = count(select(func.count()).select_from(Device).where(Device.is_mock.is_(True)))
    orders = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    jobs = dict(db.execute(select(TestJob.status, func.count()).group_by(TestJob.status)).all())
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    res = dict(db.execute(select(TestResult.status, func.count()).where(TestResult.created_at >= today, TestResult.is_mock.is_(False))
                          .group_by(TestResult.status)).all())
    month = today.replace(day=1)
    paid, refunded = db.execute(select(func.coalesce(func.sum(Payment.amount), 0), func.coalesce(func.sum(Payment.refunded_amount), 0))
                                .where(Payment.mode != "mock", Payment.approved_at >= month,
                                       Payment.status.in_(["paid", "partial_refunded", "refunded"]))).one()
    daily = [{"day": d.strftime("%Y-%m-%d"), "count": n, "amount": int(a or 0), "refunded": int(r or 0)}
             for d, n, a, r in revenue_rows(db, "day", False, now - timedelta(days=30))]
    return {"customers": count(select(func.count()).select_from(Customer)),
            "apps": count(select(func.count()).select_from(App).where(App.deleted_at.is_(None))),
            "orders": orders, "jobs": jobs, "devices": dev, "devices_total": sum(dev.values()), "mock_devices": mock_dev,
            "agents_online": count(select(func.count()).select_from(Agent).where(Agent.status == "online")),
            "agents_total": count(select(func.count()).select_from(Agent).where(Agent.status != "revoked")),
            "results_today": res, "month_revenue": int(paid) - int(refunded),
            "open_tickets": count(select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "open")),
            "waiting_plans": count(select(func.count()).select_from(TestPlan).where(TestPlan.status == "waiting_devices")),
            "payment": settings_store.payment_state(db), "smtp_configured": settings_store.smtp_configured(db),
            "ai_configured": analysis.ai_configured(db), "daily_revenue": list(reversed(daily)),
            "secret_key_ephemeral": settings.SECRET_KEY_IS_EPHEMERAL}


# ---------------- 고객 / 회원 / 권한 ----------------
@router.get("/customers")
def customers(q: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("customers"))):
    stmt = select(Customer).join(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like), func.lower(Customer.company).like(like)))
    out = []
    for c in db.scalars(stmt.order_by(Customer.id.desc()).limit(500)):
        orders, spent = db.execute(select(func.count(), func.coalesce(func.sum(Order.final_amount), 0))
                                   .where(Order.customer_id == c.id, Order.paid_at.isnot(None), Order.is_mock.is_(False))).one()
        out.append({"id": c.id, "user_id": c.user_id, "email": c.user.email, "name": c.user.name, "kind": c.kind,
                    "company": c.company, "phone": c.phone, "is_active": c.user.is_active, "email_verified": c.user.email_verified,
                    "created_at": c.created_at, "last_login_at": c.user.last_login_at, "paid_orders": orders, "spent": int(spent),
                    "apps": db.scalar(select(func.count()).select_from(App).where(App.customer_id == c.id, App.deleted_at.is_(None)))})
    return out


@router.get("/customers/{cid}")
def customer_detail(cid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("customers"))):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "고객을 찾을 수 없습니다.")
    apps = db.scalars(select(App).where(App.customer_id == cid, App.deleted_at.is_(None))).all()
    orders = db.scalars(select(Order).where(Order.customer_id == cid).order_by(Order.id.desc()).limit(100)).all()
    logins = db.scalars(select(LoginHistory).where(LoginHistory.user_id == c.user_id).order_by(LoginHistory.id.desc()).limit(20)).all()
    return {"customer": {**row_dict(c), "user": user_view(c.user), "is_active": c.user.is_active},
            "apps": [app_view(a) for a in apps], "orders": [order_view(db, o) for o in orders],
            "logins": [{"at": r.created_at, "ip": r.ip, "success": r.success, "reason": r.reason} for r in logins]}


@router.get("/users")
def users(staff_only: bool = False, db: Session = Depends(get_db), _: User = Depends(require_perm("users"))):
    stmt = select(User).join(Role).where(User.deleted_at.is_(None))
    if staff_only:
        stmt = stmt.where(Role.is_staff.is_(True))
    return [{**user_view(u), "is_active": u.is_active, "locked": bool(u.locked_until and u.locked_until > utcnow()),
             "last_login_at": u.last_login_at, "created_at": u.created_at} for u in db.scalars(stmt.order_by(User.id.desc()).limit(1000))]


class StaffIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=60)
    name: str
    password: str
    role: str


@router.post("/users")
def create_staff(body: StaffIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("users"))):
    role = db.scalar(select(Role).where(Role.code == body.role, Role.is_staff.is_(True)))
    if not role:
        raise HTTPException(400, "관리자 역할을 선택해 주세요.")
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    new = User(email=body.email.lower(), username=body.username.lower(), name=body.name, role_id=role.id,
               password_hash=hash_password(body.password), email_verified=True, must_change_password=True)
    db.add(new)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "이미 사용 중인 이메일 또는 아이디입니다.") from exc
    audit(db, user.id, "user.create_staff", "user", new.id, {"role": role.code}, client_ip(request))
    db.commit()
    return user_view(new)


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    unlock: bool = False
    new_password: str | None = None


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_staff)):
    target = db.get(User, uid)
    if not target or target.deleted_at:
        raise HTTPException(404, "회원을 찾을 수 없습니다.")
    need = "users" if (target.role.is_staff or body.role) else "customers"
    if not has_perm(user, need):
        raise HTTPException(403, "이 작업에 대한 권한이 없습니다.")
    if target.id == user.id and (body.is_active is False or body.role):
        raise HTTPException(400, "본인 계정의 권한·활성 상태는 변경할 수 없습니다.")
    if body.role:
        role = db.scalar(select(Role).where(Role.code == body.role))
        if not role or role.is_staff != target.role.is_staff:
            raise HTTPException(400, "고객 ↔ 관리자 간 역할 전환은 할 수 없습니다.")
        target.role_id = role.id
    if body.is_active is not None:
        target.is_active = body.is_active
        if not body.is_active:
            revoke_sessions(db, target.id)
    if body.unlock:
        target.locked_until, target.failed_logins = None, 0
    if body.new_password:
        if problem := password_problem(body.new_password):
            raise HTTPException(400, problem)
        target.password_hash, target.must_change_password = hash_password(body.new_password), True
        revoke_sessions(db, target.id)
    audit(db, user.id, "user.update", "user", uid, body.model_dump(exclude={"new_password"}, exclude_none=True), client_ip(request))
    db.commit()
    db.refresh(target)
    return {**user_view(target), "is_active": target.is_active}


@router.get("/roles")
def roles(db: Session = Depends(get_db), _: User = Depends(require_perm("users"))):
    return {"roles": [{"id": r.id, "code": r.code, "name": r.name, "is_staff": r.is_staff,
                       "permissions": [p.code for p in r.permissions]} for r in db.scalars(select(Role).order_by(Role.id))],
            "permissions": [{"code": p.code, "name": p.name} for p in db.scalars(select(Permission).order_by(Permission.id))]}


class RolePerms(BaseModel):
    permissions: list[str]


@router.put("/roles/{code}")
def set_role_permissions(code: str, body: RolePerms, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require_perm("users"))):
    role = db.scalar(select(Role).where(Role.code == code))
    if not role or not role.is_staff or role.code == "superadmin":
        raise HTTPException(400, "이 역할의 권한은 변경할 수 없습니다.")
    role.permissions = db.scalars(select(Permission).where(Permission.code.in_(body.permissions))).all()
    audit(db, user.id, "role.update", "role", code, {"permissions": body.permissions}, client_ip(request))
    db.commit()
    return {"ok": True}


# ---------------- 앱 / 주문 ----------------
@router.get("/apps")
def apps(db: Session = Depends(get_db), _: User = Depends(require_perm("orders"))):
    rows = db.execute(select(App, User.email).join(Customer, Customer.id == App.customer_id).join(User, User.id == Customer.user_id)
                      .where(App.deleted_at.is_(None)).order_by(App.id.desc()).limit(500)).all()
    return [{**app_view(a), "customer_email": email, "customer_id": a.customer_id} for a, email in rows]


@router.get("/files/quarantine")
def quarantine(db: Session = Depends(get_db), _: User = Depends(require_perm("orders"))):
    rows = db.scalars(select(AppFile).where(AppFile.status == "quarantined").order_by(AppFile.id.desc()).limit(300))
    return [row_dict(f) for f in rows]


@router.delete("/files/quarantine/{fid}")
def delete_quarantined(fid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("orders"))):
    f = db.get(AppFile, fid)
    if not f or f.status != "quarantined":
        raise HTTPException(404, "격리 파일을 찾을 수 없습니다.")
    storage.remove(f.path)
    db.delete(f)
    audit(db, user.id, "file.delete_quarantined", "app_file", fid, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/orders")
def orders(status: str = "", q: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("orders"))):
    stmt = select(Order, User.email).join(Customer, Customer.id == Order.customer_id).join(User, User.id == Customer.user_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if q:
        stmt = stmt.where(or_(Order.order_no.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    return [{**order_view(db, o), "customer_email": email} for o, email in db.execute(stmt.order_by(Order.id.desc()).limit(500)).all()]


@router.get("/orders/{oid}")
def order_detail(oid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("orders"))):
    o = db.get(Order, oid)
    if not o:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    c = db.get(Customer, o.customer_id)
    return {**order_view(db, o, True), "customer_email": c.user.email, "customer_name": c.user.name}


@router.post("/orders/{oid}/cancel")
def cancel_order(oid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("orders"))):
    """미결제 주문 취소 또는 진행 중 검사 중단(환불은 결제 관리에서 별도 처리)."""
    o = db.scalar(select(Order).where(Order.id == oid).with_for_update(of=Order))
    if not o or o.status in ("completed", "cancelled", "refunded"):
        raise HTTPException(400, "취소할 수 없는 주문입니다.")
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == o.id))
    if plan and plan.status not in ("completed", "cancelled"):
        order_svc.stop_plan(db, plan, "cancelled")
    o.status = "cancelled"
    audit(db, user.id, "order.cancel", "order", oid, ip=client_ip(request))
    db.commit()
    return {"ok": True}


# ---------------- 결제 관리 ----------------
@router.get("/payments")
def payments(status: str = "", mode: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    stmt = select(Payment)
    if status:
        stmt = stmt.where(Payment.status == status)
    if mode:
        stmt = stmt.where(Payment.mode == mode)
    return [payment_view(p) for p in db.scalars(stmt.order_by(Payment.id.desc()).limit(500))]


@router.get("/payments/{pid}")
def payment_detail(pid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    p = db.get(Payment, pid)
    if not p:
        raise HTTPException(404, "결제를 찾을 수 없습니다.")
    refunds = db.scalars(select(Refund).where(Refund.payment_id == pid).order_by(Refund.id)).all()
    events = db.scalars(select(PaymentEvent).where(PaymentEvent.payment_id == pid).order_by(PaymentEvent.id)).all()
    return {**payment_view(p), "raw": p.raw, "refunds": [row_dict(r) for r in refunds], "events": [row_dict(e) for e in events]}


@router.get("/payment-events")
def payment_events(db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    return [row_dict(e) for e in db.scalars(select(PaymentEvent).order_by(PaymentEvent.id.desc()).limit(200))]


class RefundIn(BaseModel):
    amount: int | None = None
    reason: str = ""
    idempotency_key: str = Field(min_length=8, max_length=80)


@router.post("/payments/{pid}/refund")
def refund(pid: int, body: RefundIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("payments"))):
    r = order_svc.refund_payment(db, pid, body.amount, body.reason, user.id, body.idempotency_key)
    audit(db, user.id, "payment.refund", "payment", pid, {"amount": r.amount, "reason": body.reason}, client_ip(request))
    db.commit()
    return row_dict(r)


@router.get("/refunds")
def refunds(db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    rows = db.execute(select(Refund, Payment).join(Payment, Payment.id == Refund.payment_id).order_by(Refund.id.desc()).limit(300)).all()
    return [{**row_dict(r), "order_no": p.order.order_no, "mode": p.mode} for r, p in rows]


@router.get("/revenue")
def revenue(unit: str = "day", db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    """매출 집계. 모의 결제는 실매출과 완전히 분리해 별도 항목으로만 표시한다."""
    if unit not in ("day", "month", "year"):
        raise HTTPException(400, "unit은 day, month, year 중 하나여야 합니다.")
    fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[unit]
    shape = lambda rows: [{"period": d.strftime(fmt), "count": n, "amount": int(a or 0), "refunded": int(r or 0),  # noqa: E731
                           "net": int(a or 0) - int(r or 0)} for d, n, a, r in rows if d]
    return {"unit": unit, "real": shape(revenue_rows(db, unit, False)), "mock": shape(revenue_rows(db, unit, True))}


class PgIn(BaseModel):
    provider: str = "toss"
    mode: str
    client_key: str | None = None
    secret_key: str | None = None


@router.get("/pg")
def pg_get(request: Request, db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    from .auth import base_url
    base = base_url(request)
    return {"state": settings_store.payment_state(db), "settings": settings_store.masked_view(db, "pg."),
            "webhook_url": f"{base}/api/payments/webhook/toss", "success_url": f"{base}/pay/success", "fail_url": f"{base}/pay/fail",
            "providers": [{"code": "toss", "name": "토스페이먼츠"}]}


@router.put("/pg")
def pg_put(body: PgIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("payments"))):
    if body.mode not in ("disabled", "mock", "test", "live"):
        raise HTTPException(400, "모드는 disabled, mock, test, live 중 하나여야 합니다.")
    if body.client_key is not None:
        settings_store.put(db, "pg.toss.client_key", body.client_key.strip())
    if body.secret_key:
        settings_store.put(db, "pg.toss.secret_key", body.secret_key.strip())
    db.commit()  # 키는 먼저 저장하고, 모드 전환은 아래 검증을 통과해야 반영된다
    ck, sk = settings_store.get(db, "pg.toss.client_key"), settings_store.get(db, "pg.toss.secret_key")
    if body.mode in ("test", "live"):
        if not ck or not sk:
            raise HTTPException(400, "Client Key와 Secret Key를 먼저 등록해 주세요.")
        want = "test_" if body.mode == "test" else "live_"
        if not (ck.startswith(want) and sk.startswith(want)):
            raise HTTPException(400, f"{body.mode} 모드에는 '{want}'로 시작하는 키가 필요합니다.")
    settings_store.put(db, "pg.provider", body.provider)
    settings_store.put(db, "pg.mode", body.mode)
    audit(db, user.id, "pg.update", "setting", "pg", {"mode": body.mode, "provider": body.provider}, client_ip(request))
    db.commit()
    return settings_store.payment_state(db)


@router.post("/pg/test")
def pg_test(db: Session = Depends(get_db), _: User = Depends(require_perm("payments"))):
    """연동 시험: 존재하지 않는 결제를 조회해 인증 성공 여부(401 vs 404)를 확인한다. 금전 거래는 발생하지 않는다."""
    state = settings_store.payment_state(db)
    if state["mode"] == "mock":
        return {"ok": True, "message": "모의 결제 환경입니다. 실제 PG와 통신하지 않습니다."}
    if not state["has_keys"]:
        return {"ok": False, "message": "PG 인증정보가 등록되지 않았습니다. (외부 연동 대기)"}
    try:
        get_provider(db, state["mode"] if state["mode"] in ("test", "live") else "test").fetch("connection-check-0000")
    except PaymentError as exc:
        if exc.code in ("NOT_FOUND_PAYMENT", "NOT_FOUND"):
            return {"ok": True, "message": "PG 인증 성공 (시험 조회 정상 응답)"}
        return {"ok": False, "message": f"PG 응답: {exc.code} {exc.message}"}
    return {"ok": True, "message": "PG 연결 정상"}


# ---------------- 고객지원 ----------------
@router.get("/tickets")
def tickets(status: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("support"))):
    stmt = select(SupportTicket, User.email).join(Customer, Customer.id == SupportTicket.customer_id).join(User, User.id == Customer.user_id)
    if status:
        stmt = stmt.where(SupportTicket.status == status)
    return [{**ticket_view(t), "customer_email": email} for t, email in db.execute(stmt.order_by(SupportTicket.updated_at.desc()).limit(300)).all()]


@router.get("/tickets/{tid}")
def ticket(tid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("support"))):
    t = db.get(SupportTicket, tid)
    if not t:
        raise HTTPException(404, "문의를 찾을 수 없습니다.")
    return {**ticket_view(t, True), "customer_email": db.get(Customer, t.customer_id).user.email}


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    close: bool = False


@router.post("/tickets/{tid}/reply")
def reply(tid: int, body: ReplyIn, db: Session = Depends(get_db), user: User = Depends(require_perm("support"))):
    t = db.get(SupportTicket, tid)
    if not t:
        raise HTTPException(404, "문의를 찾을 수 없습니다.")
    db.add(TicketMessage(ticket_id=t.id, author_id=user.id, is_staff=True, body=body.body))
    t.status, t.updated_at = ("closed" if body.close else "answered"), utcnow()
    notifications.notify(db, db.get(Customer, t.customer_id).user_id, "ticket_answered", {"subject": t.subject},
                         f"/dashboard/support/{t.id}")
    db.commit()
    db.refresh(t)
    return ticket_view(t, True)


@router.get("/legal")
def legal_list(db: Session = Depends(get_db), _: User = Depends(require_perm("support"))):
    return [row_dict(d) for d in db.scalars(select(LegalDoc).order_by(LegalDoc.key, LegalDoc.locale))]


class LegalIn(BaseModel):
    title: str
    body: str
    locale: str = "ko"


@router.put("/legal/{key}")
def legal_put(key: str, body: LegalIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("support"))):
    if key not in ("terms", "privacy", "refund"):
        raise HTTPException(400, "문서 종류가 올바르지 않습니다.")
    doc = db.scalar(select(LegalDoc).where(LegalDoc.key == key, LegalDoc.locale == body.locale))
    if doc is None:
        doc = LegalDoc(key=key, locale=body.locale, title=body.title)
        db.add(doc)
    doc.title, doc.body, doc.updated_at = body.title, body.body, utcnow()
    audit(db, user.id, "legal.update", "legal", key, {"locale": body.locale}, client_ip(request))
    db.commit()
    return row_dict(doc)


# ---------------- 시스템 설정 ----------------
@router.get("/settings")
def settings_get(db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    return settings_store.masked_view(db)


@router.put("/settings")
def settings_put(body: dict[str, str], request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("system"))):
    """비밀값은 빈 문자열이면 기존 값을 유지한다. PG 키는 결제 관리 권한 메뉴에서만 변경한다."""
    changed = []
    for key, value in body.items():
        if key not in settings_store.DEFAULTS or key.startswith("pg."):
            raise HTTPException(400, f"변경할 수 없는 설정: {key}")
        if settings_store.DEFAULTS[key][1] and value == "":
            continue
        settings_store.put(db, key, str(value).strip())
        changed.append(key)
    audit(db, user.id, "settings.update", "setting", "", {"keys": changed}, client_ip(request))
    db.commit()
    return {"ok": True, "changed": changed}


class TestMailIn(BaseModel):
    to: EmailStr


@router.post("/settings/test-email")
def test_email(body: TestMailIn, db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    if not settings_store.smtp_configured(db):
        return {"ok": False, "message": "SMTP가 설정되지 않았습니다. (외부 연동 대기)"}
    try:
        notifications._send(db, body.to, "[구글자동테스터] SMTP 연동 시험", "SMTP 설정이 정상입니다.")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"발송 실패: {exc}"[:300]}
    return {"ok": True, "message": "시험 메일을 발송했습니다."}


@router.post("/settings/test-ai")
def test_ai(db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    return analysis.test_ai(db)


@router.get("/emails")
def emails(db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    rows = db.execute(select(Notification, User.email).join(User, User.id == Notification.user_id)
                      .where(Notification.channel == "email").order_by(Notification.id.desc()).limit(300)).all()
    counts = dict(db.execute(select(Notification.status, func.count()).where(Notification.channel == "email").group_by(Notification.status)).all())
    return {"counts": counts, "smtp_configured": settings_store.smtp_configured(db),
            "items": [{"id": n.id, "to": email, "event": n.event, "title": n.title, "status": n.status, "attempts": n.attempts,
                       "last_error": n.last_error, "sent_at": n.sent_at, "created_at": n.created_at} for n, email in rows]}


@router.get("/status")
def status(db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    from ..services import scheduler
    t0 = time.perf_counter()
    db.execute(text("select 1"))
    ping = (time.perf_counter() - t0) * 1000
    try:
        usage = shutil.disk_usage(storage.root())
        disk = {"total_mb": usage.total // 2 ** 20, "free_mb": usage.free // 2 ** 20, "path": storage.root(),
                "writable": os.access(storage.root(), os.W_OK)}
    except OSError as exc:
        disk = {"error": str(exc)}
    tables = db.execute(text("select relname, n_live_tup from pg_stat_user_tables order by relname")).all()
    return {"server": {"env": settings.ENV, "uptime_sec": int(time.time() - STARTED), "time": utcnow(),
                       "scheduler_running": scheduler._scheduler is not None, "public_base_url": settings.PUBLIC_BASE_URL},
            "database": {"ok": True, "ping_ms": round(ping, 2),
                         "size_mb": round((db.scalar(text("select pg_database_size(current_database())")) or 0) / 2 ** 20, 1),
                         "version": db.scalar(text("show server_version")),
                         "migration": db.scalar(text("select version_num from alembic_version")) if
                         db.scalar(text("select to_regclass('alembic_version')")) else None,
                         "tables": [{"name": n, "rows": r} for n, r in tables]},
            "storage": disk}


@router.get("/audit-logs")
def audit_logs(db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    rows = db.execute(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.actor_id)
                      .order_by(AuditLog.id.desc()).limit(500)).all()
    return [{**row_dict(a), "actor": email} for a, email in rows]


@router.get("/system-logs")
def system_logs(level: str = "", db: Session = Depends(get_db), _: User = Depends(require_staff)):
    stmt = select(SystemLog)
    if level:
        stmt = stmt.where(SystemLog.level == level)
    return [row_dict(r) for r in db.scalars(stmt.order_by(SystemLog.id.desc()).limit(500))]


# ---------------- 백업 / 복구 ----------------
def _json_default(v):
    if isinstance(v, (datetime, date)):
        return {"__dt__": v.isoformat()}
    if isinstance(v, Decimal):
        return float(v)
    raise TypeError(str(type(v)))


def create_backup(db: Session, actor_id: int | None, kind: str = "manual") -> BackupHistory:
    """전체 테이블을 JSON(gzip)으로 내보낸다. 업로드 파일(APK·스크린샷)은 볼륨 스냅샷으로 별도 백업한다."""
    storage.ensure_dirs()
    data = {"created_at": utcnow().isoformat(), "tables": {}}
    for table in Base.metadata.sorted_tables:
        data["tables"][table.name] = [dict(r._mapping) for r in db.execute(table.select())]
    rel = f"backups/backup-{utcnow():%Y%m%d-%H%M%S}-{os.urandom(3).hex()}.json.gz"
    with gzip.open(storage.abspath(rel), "wt", encoding="utf-8") as fh:
        json.dump(data, fh, default=_json_default, ensure_ascii=False)
    row = BackupHistory(kind=kind, path=rel, size=os.path.getsize(storage.abspath(rel)), created_by=actor_id,
                        note=f"{sum(len(v) for v in data['tables'].values())} rows")
    db.add(row)
    db.flush()
    return row


def restore_backup(db: Session, full_path: str) -> int:
    with gzip.open(full_path, "rt", encoding="utf-8") as fh:
        data = json.load(fh, object_hook=lambda d: datetime.fromisoformat(d["__dt__"]) if "__dt__" in d else d)
    tables = Base.metadata.sorted_tables
    names = ", ".join(f'"{t.name}"' for t in tables)
    db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    total = 0
    for table in tables:
        rows = data["tables"].get(table.name) or []
        cols = set(table.columns.keys())
        rows = [{k: v for k, v in r.items() if k in cols} for r in rows]
        for i in range(0, len(rows), 500):
            db.execute(table.insert(), rows[i:i + 500])
        total += len(rows)
        if "id" in cols and isinstance(table.columns["id"].type, Integer):
            db.execute(text(f"select setval(pg_get_serial_sequence('\"{table.name}\"','id'), "
                            f"coalesce((select max(id) from \"{table.name}\"), 1), "
                            f"(select count(*) > 0 from \"{table.name}\"))"))
    return total


@router.get("/backups")
def backups(db: Session = Depends(get_db), _: User = Depends(require_perm("system"))):
    return [row_dict(b) for b in db.scalars(select(BackupHistory).order_by(BackupHistory.id.desc()).limit(100))]


@router.post("/backups")
def backup_now(request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm("system"))):
    row = create_backup(db, user.id)
    audit(db, user.id, "backup.create", "backup", row.id, ip=client_ip(request))
    db.commit()
    return row_dict(row)


@router.get("/backups/{bid}/download")
def backup_download(bid: int, db: Session = Depends(get_db), user: User = Depends(require_perm("system"))):
    row = db.get(BackupHistory, bid)
    if not row or not row.path:
        raise HTTPException(404, "백업을 찾을 수 없습니다.")
    return FileResponse(storage.abspath(row.path), media_type="application/gzip", filename=os.path.basename(row.path))


class RestoreIn(BaseModel):
    confirm: str


@router.post("/backups/{bid}/restore")
def backup_restore(bid: int, body: RestoreIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    if user.role.code != "superadmin":
        raise HTTPException(403, "최고관리자만 복구할 수 있습니다.")
    if body.confirm != "RESTORE":
        raise HTTPException(400, "확인 문구(RESTORE)를 입력해 주세요.")
    row = db.get(BackupHistory, bid)
    if not row or not row.path:
        raise HTTPException(404, "백업을 찾을 수 없습니다.")
    path, actor = storage.abspath(row.path), user.id
    safety = create_backup(db, actor, "pre_restore")  # 복구 직전 상태를 자동 보관
    db.commit()
    safety_path, safety_size = safety.path, safety.size
    db.expunge_all()
    total = restore_backup(db, path)
    db.expunge_all()
    db.add(BackupHistory(kind="pre_restore", path=safety_path, size=safety_size, note="복구 직전 자동 백업"))
    db.add(BackupHistory(kind="restore", path="", status="done", note=f"{total} rows 복구"))
    audit(db, None, "backup.restore", "backup", bid, {"rows": total}, client_ip(request))
    db.commit()
    return {"ok": True, "rows": total}
