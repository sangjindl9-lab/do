"""주문 → 결제 확정 → 검사 계획 → 기기 배정 → 작업 생성까지의 자동 처리."""
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (App, AppVersion, Coupon, Customer, Device, DeviceAssignment, DeviceCommand, Order, Payment,
                      Product, Refund, TestJob, TestPlan, TestScenario, TestSchedule)
from ..security import decrypt
from . import settings_store
from .audit import syslog
from .notifications import notify, notify_staff
from .payment_providers import MockProvider, PaymentError, get_provider

ELIGIBLE_STATUS = ("idle", "assigned", "testing", "online")
ACTIVE_PLAN = ("scheduled", "running", "paused")


def new_order_no() -> str:
    return "GAT" + utcnow().strftime("%y%m%d") + secrets.token_hex(4).upper()


def coupon_discount(db: Session, code: str, product: Product, lock: bool = False) -> tuple[Coupon | None, int]:
    if not code:
        return None, 0
    stmt = select(Coupon).where(func.upper(Coupon.code) == code.strip().upper())
    coupon = db.scalar(stmt.with_for_update(of=Coupon) if lock else stmt)
    now = utcnow()
    if not coupon or not coupon.is_active:
        raise HTTPException(400, "사용할 수 없는 쿠폰입니다.")
    if not product.coupon_allowed:
        raise HTTPException(400, "이 상품에는 쿠폰을 적용할 수 없습니다.")
    if (coupon.valid_from and coupon.valid_from > now) or (coupon.valid_to and coupon.valid_to < now):
        raise HTTPException(400, "쿠폰 사용 기간이 아닙니다.")
    if coupon.max_uses and coupon.used_count >= coupon.max_uses:
        raise HTTPException(400, "쿠폰 사용 한도가 소진되었습니다.")
    if product.price < coupon.min_amount:
        raise HTTPException(400, "쿠폰 최소 결제금액 조건을 충족하지 않습니다.")
    discount = product.price * coupon.value // 100 if coupon.kind == "percent" else coupon.value
    return coupon, max(0, min(discount, product.price))


def create_order(db: Session, customer: Customer, data: dict, idempotency_key: str | None) -> Order:
    if idempotency_key:
        existing = db.scalar(select(Order).where(Order.idempotency_key == idempotency_key))
        if existing:
            if existing.customer_id != customer.id:
                raise HTTPException(409, "중복된 요청 키입니다.")
            return existing
    app = db.get(App, data["app_id"])
    if not app or app.customer_id != customer.id or app.deleted_at:
        raise HTTPException(404, "앱을 찾을 수 없습니다.")
    if not app.ownership_confirmed:
        raise HTTPException(400, "앱 검사 권한 확인이 필요합니다.")
    version = db.get(AppVersion, data["app_version_id"])
    if not version or version.app_id != app.id:
        raise HTTPException(404, "앱 버전을 찾을 수 없습니다.")
    if version.file and version.file.status != "clean":
        raise HTTPException(400, "격리된 파일은 검사할 수 없습니다.")
    product = db.get(Product, data["product_id"])
    if not product or not product.is_active:
        raise HTTPException(404, "판매 중인 상품이 아닙니다.")
    if product.is_quote:
        raise HTTPException(400, "별도 견적 상품입니다. 고객 문의로 요청해 주세요.")
    scenario_id = data.get("scenario_id")
    if scenario_id:
        sc = db.get(TestScenario, scenario_id)
        if not sc or sc.customer_id not in (None, customer.id):
            raise HTTPException(404, "검사 시나리오를 찾을 수 없습니다.")
    coupon, discount = coupon_discount(db, data.get("coupon_code") or "", product)
    snapshot = {c.name: getattr(product, c.name) for c in Product.__table__.columns}
    order = Order(order_no=new_order_no(), customer_id=customer.id, app_id=app.id, app_version_id=version.id,
                  product_id=product.id, product_snapshot=snapshot, scenario_id=scenario_id,
                  amount=product.price, discount=discount, coupon_id=coupon.id if coupon else None,
                  final_amount=product.price - discount, desired_start=data.get("desired_start"),
                  desired_android=(data.get("desired_android") or "")[:20], request_notes=data.get("request_notes") or "",
                  idempotency_key=idempotency_key)
    db.add(order)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Order).where(Order.idempotency_key == idempotency_key))
    notify(db, customer.user_id, "order_received", {"order_no": order.order_no, "app": app.name}, f"/dashboard/orders/{order.id}")
    return order


# ---------------- 결제 ----------------
def confirm_payment(db: Session, order_no: str, payment_key: str, amount: int) -> Payment:
    """서버 측 금액 검증 + PG 승인 + 주문 확정. 주문 행 잠금으로 중복 결제를 차단한다."""
    order = db.scalar(select(Order).where(Order.order_no == order_no).with_for_update(of=Order))
    if not order:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    paid = db.scalar(select(Payment).where(Payment.order_id == order.id,
                                           Payment.status.in_(["paid", "partial_refunded", "refunded"])))
    if paid:
        if paid.payment_key == payment_key:
            return paid  # 멱등: 같은 결제의 재요청
        raise HTTPException(409, "이미 결제가 완료된 주문입니다.")
    if order.status != "pending_payment":
        raise HTTPException(409, "결제할 수 없는 주문 상태입니다.")
    state = settings_store.payment_state(db)
    if not state["enabled"]:
        raise HTTPException(503, "결제가 비활성화되어 있습니다.")
    payment = db.scalar(select(Payment).where(Payment.payment_key == payment_key))
    if payment and payment.order_id != order.id:
        raise HTTPException(409, "다른 주문에 사용된 결제입니다.")
    if payment is None:
        payment = db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.status == "ready",
                                                  Payment.payment_key.is_(None)))
    if payment is None:
        payment = Payment(order_id=order.id, provider=state["provider"], mode=state["mode"], amount=order.final_amount)
        db.add(payment)
    payment.payment_key, payment.provider, payment.mode = payment_key, state["provider"], state["mode"]

    def fail(code: str, message: str, http: int):
        payment.status, payment.failure_code, payment.failure_message = "failed", code, message[:500]
        notify(db, order.customer.user_id if hasattr(order, "customer") else _owner(db, order), "payment_failed",
               {"order_no": order.order_no, "reason": message})
        db.commit()
        raise HTTPException(http, message)

    if amount != order.final_amount:
        fail("AMOUNT_MISMATCH", "결제 금액이 주문 금액과 일치하지 않습니다.", 400)
    try:
        result = get_provider(db).confirm(payment_key, order.order_no, order.final_amount)
    except PaymentError as exc:
        fail(exc.code, exc.message, 402)
    if result["amount"] != order.final_amount or result["order_no"] != order.order_no or result["status"] != "DONE":
        fail("PG_RESULT_MISMATCH", "PG 승인 결과가 주문 정보와 일치하지 않습니다.", 400)
    payment.status, payment.method, payment.receipt_url = "paid", result["method"], result["receipt_url"]
    payment.raw, payment.approved_at, payment.amount = result["raw"], utcnow(), result["amount"]
    payment.failure_code = payment.failure_message = ""
    on_payment_confirmed(db, order, payment)
    return payment


def _owner(db: Session, order: Order) -> int:
    return db.get(Customer, order.customer_id).user_id


def on_payment_confirmed(db: Session, order: Order, payment: Payment) -> TestPlan:
    now = utcnow()
    order.status, order.paid_at, order.is_mock = "paid", now, payment.mode == "mock"
    if order.coupon_id:
        db.execute(update(Coupon).where(Coupon.id == order.coupon_id).values(used_count=Coupon.used_count + 1))
    snap = order.product_snapshot
    start = max(now, order.desired_start) if order.desired_start else now
    plan = TestPlan(order_id=order.id, customer_id=order.customer_id, app_id=order.app_id,
                    app_version_id=order.app_version_id, scenario_id=order.scenario_id,
                    device_count=snap["device_count"], daily_runs=max(1, snap["daily_runs"]), checks=snap["checks"] or [],
                    desired_android=order.desired_android, start_at=start,
                    end_at=start + timedelta(days=snap["duration_days"]), status="waiting_devices",
                    priority=10 if snap.get("priority") else 0, is_mock=order.is_mock)
    db.add(plan)
    db.flush()
    # 배정 직후 1회(설치) 실행하고, 이후에는 매일 한국시간 오전 2시(UTC 17:00)부터 일일 횟수만큼 실행한다.
    times = {1: ["17:00"], 2: ["17:00", "05:00"], 3: ["17:00", "01:00", "09:00"]}.get(plan.daily_runs, [])
    db.add(TestSchedule(plan_id=plan.id, run_times=times, next_run_at=start, status="active"))
    db.flush()
    owner = _owner(db, order)
    notify(db, owner, "payment_done", {"order_no": order.order_no, "amount": f"{payment.amount:,}"},
           f"/dashboard/orders/{order.id}")
    allocate_plan(db, plan)
    return plan


def allocate_plan(db: Session, plan: TestPlan) -> bool:
    """가용 기기 검색 → 호환성 확인 → 자동 배정. 부족하면 대기 상태를 유지한다(전량 확보 시 배정)."""
    if plan.status not in ("waiting_devices",):
        return True
    max_plans = settings_store.get_int(db, "limits.max_plans_per_device")
    load = (select(DeviceAssignment.device_id, func.count().label("n"))
            .join(TestPlan, TestPlan.id == DeviceAssignment.plan_id)
            .where(DeviceAssignment.status == "active", TestPlan.status.in_(ACTIVE_PLAN))
            .group_by(DeviceAssignment.device_id).subquery())
    stmt = (select(Device).outerjoin(load, load.c.device_id == Device.id)
            .where(Device.enabled.is_(True), Device.maintenance.is_(False), Device.is_mock == plan.is_mock,
                   Device.status.in_(ELIGIBLE_STATUS), func.coalesce(load.c.n, 0) < max_plans)
            .order_by(func.coalesce(load.c.n, 0), Device.id).limit(plan.device_count)
            .with_for_update(of=Device, skip_locked=True))
    if plan.desired_android:
        stmt = stmt.where(Device.android_version.like(plan.desired_android.split(".")[0] + "%"))
    devices = db.scalars(stmt).unique().all()
    order = plan.order
    if len(devices) < plan.device_count:
        if order.status != "waiting_devices":
            order.status = "waiting_devices"
            notify(db, _owner(db, order), "test_delayed",
                   {"order_no": order.order_no, "reason": "가용 검사 기기가 부족하여 배정 대기 중입니다. 기기가 확보되면 자동으로 시작됩니다."})
            notify_staff(db, "test_delayed", {"order_no": order.order_no,
                                              "reason": f"가용 기기 부족 (필요 {plan.device_count}대, 가용 {len(devices)}대)"})
        return False
    now = utcnow()
    if plan.start_at < now:  # 대기했던 만큼 검사 기간을 뒤로 민다(고객 검사 기간 보장)
        duration = plan.end_at - plan.start_at
        plan.start_at, plan.end_at = now, now + duration
    for dev in devices:
        db.add(DeviceAssignment(plan_id=plan.id, device_id=dev.id))
        if dev.status == "idle":
            dev.status = "assigned"
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == plan.id))
    sched.next_run_at = plan.start_at
    plan.status, order.status = "scheduled", "scheduled"
    notify(db, _owner(db, order), "devices_assigned", {"order_no": order.order_no, "count": len(devices)},
           f"/dashboard/orders/{order.id}")
    return True


def build_payload(db: Session, plan: TestPlan) -> dict:
    version = plan.app_version
    app = plan.app
    apk = None
    if version.file and version.file.status == "clean":
        apk = {"file_id": version.file.id, "sha256": version.file.sha256, "size": version.file.size}
    scenario = db.get(TestScenario, plan.scenario_id) if plan.scenario_id else None
    variables = {}
    if app.test_login_enc and scenario:
        try:
            import json
            variables = json.loads(decrypt(app.test_login_enc) or "{}")
        except ValueError:
            variables = {}
    return {"package": app.package_name, "app_name": app.name, "version_name": version.version_name,
            "version_code": version.version_code, "apk": apk, "checks": plan.checks or [],
            "scenario": {"id": scenario.id, "name": scenario.name, "version": scenario.version,
                         "steps": scenario.steps} if scenario else None,
            "vars": variables}


def create_jobs_for_run(db: Session, plan: TestPlan, run_key: str, kind: str = "scheduled") -> int:
    """배정된 기기마다 검사 작업 생성. (plan, device, run_key) 유일성 제약으로 중복 실행을 방지한다."""
    from sqlalchemy.dialects.postgresql import insert
    payload = build_payload(db, plan)
    assigns = db.scalars(select(DeviceAssignment).where(DeviceAssignment.plan_id == plan.id,
                                                        DeviceAssignment.status == "active")).all()
    timeout = settings_store.get_int(db, "limits.job_timeout_sec")
    attempts = settings_store.get_int(db, "limits.job_max_attempts")
    created = 0
    for a in assigns:
        stmt = insert(TestJob).values(
            plan_id=plan.id, device_id=a.device_id, agent_id=a.device.agent_id, app_version_id=plan.app_version_id,
            run_key=run_key, kind=kind, status="queued", priority=plan.priority, payload=payload, attempts=0,
            max_attempts=attempts, timeout_sec=timeout, next_attempt_at=utcnow(), is_mock=plan.is_mock, progress=0,
            error="", created_at=utcnow()).on_conflict_do_nothing(constraint="uq_job_plan_device_run").returning(TestJob.id)
        created += len(db.execute(stmt).all())
    return created


def stop_plan(db: Session, plan: TestPlan, status: str) -> None:
    """검사 계획 종료(취소/완료): 대기 작업 취소, 기기 배정 해제, 기기 내 고객 앱 정리 명령 예약."""
    db.execute(update(TestJob).where(TestJob.plan_id == plan.id, TestJob.status.in_(["queued", "leased", "running"]))
               .values(status="cancelled", finished_at=utcnow(), error="검사 계획 종료"))
    cleanup = settings_store.get(db, "retention.cleanup_app_after_test") == "1"
    for a in db.scalars(select(DeviceAssignment).where(DeviceAssignment.plan_id == plan.id,
                                                       DeviceAssignment.status == "active")):
        a.status, a.released_at = "released", utcnow()
        if cleanup:
            db.add(DeviceCommand(device_id=a.device_id, agent_id=a.device.agent_id, type="uninstall",
                                 params={"package": plan.app.package_name, "reason": "검사 종료 후 고객 데이터 정리"}))
    sched = db.scalar(select(TestSchedule).where(TestSchedule.plan_id == plan.id))
    if sched:
        sched.status, sched.next_run_at = "done", None
    plan.status = status


def refund_payment(db: Session, payment_id: int, amount: int | None, reason: str, actor_id: int | None,
                   idempotency_key: str) -> Refund:
    """전체/부분 환불. 결제 행 잠금 + 멱등 키로 중복 환불을 방지한다."""
    existing = db.scalar(select(Refund).where(Refund.idempotency_key == idempotency_key))
    if existing:
        return existing
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update(of=Payment))
    if not payment or payment.status not in ("paid", "partial_refunded"):
        raise HTTPException(400, "환불할 수 없는 결제입니다.")
    remain = payment.amount - payment.refunded_amount
    amt = remain if amount is None else amount
    if amt <= 0 or amt > remain:
        raise HTTPException(400, f"환불 가능 금액({remain:,}원)을 확인해 주세요.")
    try:
        result = get_provider(db, payment.mode).cancel(payment.payment_key, None if amt == remain and payment.refunded_amount == 0 else amt,
                                                       reason, idempotency_key)
    except PaymentError as exc:
        syslog(db, "error", "payment", f"환불 실패 payment={payment.id}: {exc.code} {exc.message}")
        db.commit()
        raise HTTPException(402, f"PG 환불 실패: {exc.message}") from exc
    refund = Refund(payment_id=payment.id, amount=amt, reason=reason, provider_ref=result.get("cancel_ref", ""),
                    idempotency_key=idempotency_key, requested_by=actor_id)
    db.add(refund)
    payment.refunded_amount += amt
    order = payment.order
    full = payment.refunded_amount >= payment.amount
    payment.status = "refunded" if full else "partial_refunded"
    if full:
        plan = db.scalar(select(TestPlan).where(TestPlan.order_id == order.id))
        if plan and plan.status not in ("completed", "cancelled"):
            stop_plan(db, plan, "cancelled")
        order.status = "refunded"
    notify(db, _owner(db, order), "refund_done", {"order_no": order.order_no, "amount": f"{amt:,}"},
           f"/dashboard/orders/{order.id}")
    return refund


def issue_mock_payment(order: Order, outcome: str) -> str:
    key = "mock_" + secrets.token_hex(12)
    MockProvider.issue(key, order.order_no, order.final_amount, outcome)
    return key
