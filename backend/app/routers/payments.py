import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_customer
from ..models import Customer, Order, Payment, PaymentEvent
from ..services import orders as order_svc
from ..services import settings_store
from ..services.audit import syslog
from ..services.payment_providers import PaymentError, get_provider

router = APIRouter(prefix="/api/payments", tags=["payments"])


def payment_view(p: Payment) -> dict:
    return {"id": p.id, "order_id": p.order_id, "order_no": p.order.order_no, "provider": p.provider, "mode": p.mode,
            "method": p.method, "amount": p.amount, "status": p.status, "refunded_amount": p.refunded_amount,
            "receipt_url": p.receipt_url, "failure_code": p.failure_code, "failure_message": p.failure_message,
            "approved_at": p.approved_at, "created_at": p.created_at}


@router.get("/config")
def config(db: Session = Depends(get_db)):
    state = settings_store.payment_state(db)
    return {"enabled": state["enabled"], "provider": state["provider"], "mode": state["mode"], "client_key": state["client_key"]}


class PrepareIn(BaseModel):
    order_id: int


@router.post("/prepare")
def prepare(body: PrepareIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    """결제 요청 준비. 금액은 항상 서버의 주문 금액을 사용한다."""
    state = settings_store.payment_state(db)
    if not state["enabled"]:
        raise HTTPException(503, "현재 결제가 비활성화되어 있습니다. (PG 인증정보 미등록)")
    order = db.scalar(select(Order).where(Order.id == body.order_id, Order.customer_id == customer.id).with_for_update(of=Order))
    if not order:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    if order.status != "pending_payment":
        raise HTTPException(409, "이미 결제되었거나 결제할 수 없는 주문입니다.")
    ready = db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.status == "ready",
                                            Payment.payment_key.is_(None)))
    if not ready:
        db.add(Payment(order_id=order.id, provider=state["provider"], mode=state["mode"], amount=order.final_amount))
    db.commit()
    return {"order_no": order.order_no, "amount": order.final_amount, "order_name": f"{order.product_snapshot['name']} - {order.app.name}"[:100],
            "customer_key": f"gat-customer-{customer.id}", "provider": state["provider"], "mode": state["mode"],
            "client_key": state["client_key"]}


class ConfirmIn(BaseModel):
    paymentKey: str
    orderId: str
    amount: int


@router.post("/confirm")
def confirm(body: ConfirmIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.order_no == body.orderId))
    if not order or order.customer_id != customer.id:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    payment = order_svc.confirm_payment(db, body.orderId, body.paymentKey, body.amount)
    db.commit()
    return {"ok": True, "order_id": order.id, "payment": payment_view(payment)}


class FailIn(BaseModel):
    orderId: str
    code: str = ""
    message: str = ""


@router.post("/fail")
def fail(body: FailIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    """결제창에서 실패/취소된 경우의 기록."""
    order = db.scalar(select(Order).where(Order.order_no == body.orderId, Order.customer_id == customer.id))
    if not order:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    state = settings_store.payment_state(db)
    db.add(Payment(order_id=order.id, provider=state["provider"], mode=state["mode"], amount=order.final_amount,
                   status="failed", failure_code=body.code[:80], failure_message=body.message[:500]))
    db.commit()
    return {"ok": True}


class MockIn(BaseModel):
    order_id: int
    outcome: str = "success"


@router.post("/mock/issue")
def mock_issue(body: MockIn, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    """모의 결제 환경 전용: 모의 결제 키 발급(결제창 대체). 운영 모드에서는 동작하지 않는다."""
    if settings_store.get(db, "pg.mode") != "mock":
        raise HTTPException(403, "모의 결제 환경이 아닙니다.")
    order = db.get(Order, body.order_id)
    if not order or order.customer_id != customer.id:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    key = order_svc.issue_mock_payment(order, "success" if body.outcome == "success" else "fail")
    return {"paymentKey": key, "orderId": order.order_no, "amount": order.final_amount}


@router.get("")
def my_payments(customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).join(Order).where(Order.customer_id == customer.id).order_by(Payment.id.desc()).limit(200))
    return [payment_view(p) for p in rows]


def _sync_from_pg(db: Session, payment_key: str, mode: str | None = None) -> str:
    """웹훅 내용은 신뢰하지 않고 PG에 결제를 재조회하여 상태를 동기화한다."""
    try:
        remote = get_provider(db, mode).fetch(payment_key)
    except PaymentError as exc:
        return f"PG 조회 실패: {exc.code}"
    payment = db.scalar(select(Payment).where(Payment.payment_key == payment_key).with_for_update(of=Payment))
    if remote["status"] == "DONE":
        if payment and payment.status == "paid":
            return "이미 반영됨"
        try:
            order_svc.confirm_payment(db, remote["order_no"], payment_key, remote["amount"])
            return "결제 확정 동기화"
        except HTTPException as exc:
            return f"동기화 거부: {exc.detail}"
    if remote["status"] in ("CANCELED", "PARTIAL_CANCELED") and payment and payment.status in ("paid", "partial_refunded"):
        refunded = payment.amount - remote["balance"]
        delta = refunded - payment.refunded_amount
        if delta > 0:
            order_svc_refund_sync(db, payment, delta, remote)
            return "환불 동기화"
    if remote["status"] in ("ABORTED", "EXPIRED") and payment and payment.status == "ready":
        payment.status, payment.failure_code = "failed", remote["status"]
        return "실패 동기화"
    return "변경 없음"


def order_svc_refund_sync(db: Session, payment: Payment, delta: int, remote: dict) -> None:
    from ..models import Refund, TestPlan
    db.add(Refund(payment_id=payment.id, amount=delta, reason="PG 측 취소 동기화", provider_ref=remote.get("cancel_ref", ""),
                  idempotency_key=f"sync-{payment.id}-{payment.refunded_amount + delta}"))
    payment.refunded_amount += delta
    full = payment.refunded_amount >= payment.amount
    payment.status = "refunded" if full else "partial_refunded"
    if full:
        plan = db.scalar(select(TestPlan).where(TestPlan.order_id == payment.order_id))
        if plan and plan.status not in ("completed", "cancelled"):
            order_svc.stop_plan(db, plan, "cancelled")
        payment.order.status = "refunded"


def _record_event(db: Session, provider: str, event_id: str, event_type: str, payload: dict) -> PaymentEvent | None:
    event = PaymentEvent(provider=provider, event_id=event_id, event_type=event_type[:80], payload=payload)
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None  # 중복 수신
    return event


@router.post("/webhook/toss")
async def webhook_toss(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "잘못된 요청입니다.")
    data = payload.get("data") or {}
    payment_key = str(data.get("paymentKey") or "")
    if not payment_key:
        return {"ok": True, "ignored": True}
    event_id = hashlib.sha256(f"{payload.get('eventType')}|{payment_key}|{data.get('status')}|{payload.get('createdAt')}".encode()).hexdigest()
    event = _record_event(db, "toss", event_id, str(payload.get("eventType") or ""), payload)
    if event is None:
        return {"ok": True, "duplicate": True}
    event.note = _sync_from_pg(db, payment_key)
    event.processed = True
    db.commit()
    return {"ok": True}


@router.post("/webhook/mock")
async def webhook_mock(request: Request, db: Session = Depends(get_db)):
    """모의 PG 웹훅. HMAC 서명 검증 + 이벤트 ID 중복 차단을 실제와 동일하게 수행한다."""
    raw = await request.body()
    good = hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, request.headers.get("x-mock-signature", "")):
        syslog(db, "warn", "payment", "모의 웹훅 서명 검증 실패")
        db.commit()
        raise HTTPException(401, "웹훅 서명이 올바르지 않습니다.")
    payload = json.loads(raw)
    event = _record_event(db, "mock", str(payload.get("eventId")), str(payload.get("eventType") or ""), payload)
    if event is None:
        return {"ok": True, "duplicate": True}
    event.note = _sync_from_pg(db, str(payload.get("paymentKey")), "mock")
    event.processed = True
    db.commit()
    return {"ok": True, "note": event.note}
