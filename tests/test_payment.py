"""결제: 요청·모의 승인·금액 위변조 차단·중복 결제 차단·웹훅 중복·실패·취소·환불."""
import hashlib
import hmac
import json
import os
import uuid

from sqlalchemy import func, select


def retire_all(db):
    from app.models import Device
    db.execute(Device.__table__.update().values(enabled=False, status="disabled"))
    db.commit()


def test_payment_disabled_without_pg_credentials(client, customer):
    """PG 인증정보 등록 전에는 실제 결제가 비활성화되어 있어야 한다."""
    app, version = customer.make_app()
    order = customer.order(app, version)
    assert client.get("/api/payments/config").json()["enabled"] is False
    assert client.post("/api/payments/prepare", headers=customer.h, json={"order_id": order["id"]}).status_code == 503
    assert client.post("/api/payments/mock/issue", headers=customer.h, json={"order_id": order["id"]}).status_code == 403
    assert client.post("/api/payments/confirm", headers=customer.h,
                       json={"paymentKey": "x", "orderId": order["order_no"], "amount": order["final_amount"]}).status_code == 503


def test_pg_settings_validation(client, admin):
    assert client.put("/api/admin/pg", headers=admin, json={"mode": "live"}).status_code == 400          # 키 없음
    assert client.put("/api/admin/pg", headers=admin, json={"mode": "live", "client_key": "test_ck_x", "secret_key": "test_sk_x"}).status_code == 400
    view = client.get("/api/admin/pg", headers=admin).json()
    secret = next(s for s in view["settings"] if s["key"] == "pg.toss.secret_key")
    assert secret["value"] == "" and secret["is_set"]                                                   # 비밀키는 노출되지 않음
    assert view["webhook_url"].endswith("/api/payments/webhook/toss")
    client.put("/api/admin/pg", headers=admin, json={"mode": "disabled", "client_key": ""})


def test_mock_payment_success_creates_plan(client, customer, mock_pg, db):
    from app.models import Order, Payment, TestPlan
    retire_all(db)
    app, version = customer.make_app()
    order = customer.order(app, version)
    prep = client.post("/api/payments/prepare", headers=customer.h, json={"order_id": order["id"]}).json()
    assert prep["amount"] == order["final_amount"] and prep["mode"] == "mock"
    res, issued = customer.pay(order)
    assert res.status_code == 200, res.text
    pay = res.json()["payment"]
    assert pay["status"] == "paid" and pay["mode"] == "mock" and pay["amount"] == 4900
    o = db.get(Order, order["id"])
    assert o.is_mock and o.paid_at and o.status == "waiting_devices"       # 가용 기기 없음 → 자동 대기
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == o.id))
    assert plan.is_mock and plan.device_count == 5 and (plan.end_at - plan.start_at).days == 7
    # 같은 결제 재요청은 멱등 처리, 다른 결제 키로는 중복 결제 차단
    again = client.post("/api/payments/confirm", headers=customer.h, json=issued)
    assert again.status_code == 200 and again.json()["payment"]["id"] == pay["id"]
    res2, _ = customer.pay(order)
    assert res2.status_code == 409
    assert db.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == o.id, Payment.status == "paid")) == 1
    assert db.scalar(select(func.count()).select_from(TestPlan).where(TestPlan.order_id == o.id)) == 1


def test_amount_tampering_is_blocked(client, customer, mock_pg, db):
    from app.models import Order, Payment
    app, version = customer.make_app()
    order = customer.order(app, version, "PRO")
    issued = client.post("/api/payments/mock/issue", headers=customer.h, json={"order_id": order["id"]}).json()
    tampered = client.post("/api/payments/confirm", headers=customer.h, json={**issued, "amount": 100})
    assert tampered.status_code == 400
    assert db.get(Order, order["id"]).status == "pending_payment"
    failed = db.scalar(select(Payment).where(Payment.order_id == order["id"], Payment.status == "failed"))
    assert failed.failure_code == "AMOUNT_MISMATCH"
    # 다른 고객은 남의 주문을 결제 확정할 수 없다
    from conftest import Cust
    other = Cust(client)
    assert client.post("/api/payments/confirm", headers=other.h, json=issued).status_code == 404


def test_payment_failure_keeps_order_payable(client, customer, mock_pg, db):
    from app.models import Order
    app, version = customer.make_app()
    order = customer.order(app, version)
    res, _ = customer.pay(order, outcome="fail")
    assert res.status_code == 402
    assert db.get(Order, order["id"]).status == "pending_payment"
    notes = client.get("/api/notifications", headers=customer.h).json()["items"]
    assert any(n["event"] == "payment_failed" for n in notes)
    ok, _ = customer.pay(order)
    assert ok.status_code == 200
    history = client.get("/api/payments", headers=customer.h).json()
    assert sorted(p["status"] for p in history) == ["failed", "paid"]


def test_webhook_signature_and_duplicate(client, customer, mock_pg, db):
    from app.models import Order, PaymentEvent
    app, version = customer.make_app()
    order = customer.order(app, version)
    issued = client.post("/api/payments/mock/issue", headers=customer.h, json={"order_id": order["id"]}).json()
    event_id = uuid.uuid4().hex
    raw = json.dumps({"eventId": event_id, "eventType": "PAYMENT_STATUS_CHANGED", "paymentKey": issued["paymentKey"]}).encode()
    sig = hmac.new(os.environ["SECRET_KEY"].encode(), raw, hashlib.sha256).hexdigest()
    hdr = {"content-type": "application/json"}
    assert client.post("/api/payments/webhook/mock", content=raw, headers={**hdr, "x-mock-signature": "bad"}).status_code == 401
    first = client.post("/api/payments/webhook/mock", content=raw, headers={**hdr, "x-mock-signature": sig})
    assert first.status_code == 200 and first.json()["note"] == "결제 확정 동기화"   # 웹훅만으로도 상태 동기화
    db.expire_all()
    assert db.get(Order, order["id"]).paid_at is not None
    dup = client.post("/api/payments/webhook/mock", content=raw, headers={**hdr, "x-mock-signature": sig})
    assert dup.json().get("duplicate") is True                                      # 중복 수신 무시
    assert db.scalar(select(func.count()).select_from(PaymentEvent).where(PaymentEvent.event_id == event_id)) == 1
    assert client.post("/api/payments/confirm", headers=customer.h, json=issued).status_code == 200  # 멱등


def test_partial_and_full_refund(client, customer, admin, mock_pg, db):
    from app.models import Order, TestPlan
    app, version = customer.make_app()
    order = customer.order(app, version, "STANDARD")
    res, _ = customer.pay(order)
    pid = res.json()["payment"]["id"]
    key = uuid.uuid4().hex
    r1 = client.post(f"/api/admin/payments/{pid}/refund", headers=admin, json={"amount": 3000, "reason": "부분 환불", "idempotency_key": key})
    assert r1.status_code == 200 and r1.json()["amount"] == 3000
    r1b = client.post(f"/api/admin/payments/{pid}/refund", headers=admin, json={"amount": 3000, "reason": "부분 환불", "idempotency_key": key})
    assert r1b.json()["id"] == r1.json()["id"]                                       # 멱등: 이중 환불 없음
    detail = client.get(f"/api/admin/payments/{pid}", headers=admin).json()
    assert detail["status"] == "partial_refunded" and detail["refunded_amount"] == 3000
    over = client.post(f"/api/admin/payments/{pid}/refund", headers=admin, json={"amount": 9000, "idempotency_key": uuid.uuid4().hex})
    assert over.status_code == 400
    rest = client.post(f"/api/admin/payments/{pid}/refund", headers=admin, json={"reason": "전체 환불", "idempotency_key": uuid.uuid4().hex})
    assert rest.status_code == 200 and rest.json()["amount"] == 6900
    db.expire_all()
    assert db.get(Order, order["id"]).status == "refunded"
    assert db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"])).status == "cancelled"   # 결제 취소 → 검사 중단
    assert client.post(f"/api/admin/payments/{pid}/refund", headers=admin, json={"idempotency_key": uuid.uuid4().hex}).status_code == 400


def test_revenue_separates_mock_from_real(client, customer, admin, mock_pg):
    app, version = customer.make_app()
    customer.pay(customer.order(app, version))
    rev = client.get("/api/admin/revenue?unit=month", headers=admin).json()
    assert rev["real"] == []                       # 모의 결제는 실매출에 포함되지 않는다
    assert sum(r["count"] for r in rev["mock"]) >= 1
    assert client.get("/api/admin/dashboard", headers=admin).json()["month_revenue"] == 0


def test_toss_provider_request_shape():
    """토스페이먼츠 Provider가 문서 규격(Basic 인증, confirm/cancel 경로)대로 요청하는지 모의 전송 계층으로 확인."""
    import base64
    import httpx
    from app.services.payment_providers import PaymentError, TossProvider
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/confirm"):
            body = json.loads(request.content)
            return httpx.Response(200, json={"status": "DONE", "orderId": body["orderId"], "totalAmount": body["amount"],
                                             "balanceAmount": body["amount"], "method": "카드", "receipt": {"url": "https://r"}})
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "PARTIAL_CANCELED", "orderId": "O1", "totalAmount": 9900, "balanceAmount": 6900,
                                             "cancels": [{"transactionKey": "tx1"}]})
        return httpx.Response(404, json={"code": "NOT_FOUND_PAYMENT", "message": "존재하지 않는 결제"})

    toss = TossProvider("test_sk_abc", "test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    done = toss.confirm("pk1", "O1", 9900)
    assert done["status"] == "DONE" and done["amount"] == 9900 and done["receipt_url"] == "https://r"
    req = seen[0]
    assert str(req.url) == "https://api.tosspayments.com/v1/payments/confirm"
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b"test_sk_abc:").decode()
    assert json.loads(req.content) == {"paymentKey": "pk1", "orderId": "O1", "amount": 9900}
    part = toss.cancel("pk1", 3000, "부분", "idem-1")
    assert part["balance"] == 6900 and part["cancel_ref"] == "tx1"
    assert json.loads(seen[1].content) == {"cancelReason": "부분", "cancelAmount": 3000} and seen[1].headers["idempotency-key"] == "idem-1"
    try:
        toss.fetch("nope")
        raise AssertionError("should fail")
    except PaymentError as exc:
        assert exc.code == "NOT_FOUND_PAYMENT"
