"""Payment Provider 인터페이스. 토스페이먼츠 우선 지원, 다른 PG는 같은 인터페이스로 추가한다."""
import base64
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from . import settings_store


class PaymentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class PaymentProvider(Protocol):
    name: str
    mode: str

    def confirm(self, payment_key: str, order_no: str, amount: int) -> dict: ...
    def fetch(self, payment_key: str) -> dict: ...
    def cancel(self, payment_key: str, amount: int | None, reason: str, idempotency_key: str) -> dict: ...


def _normalize_toss(data: dict) -> dict:
    cancels = data.get("cancels") or []
    return {"status": data.get("status", ""), "order_no": data.get("orderId", ""),
            "amount": int(data.get("totalAmount") or 0), "balance": int(data.get("balanceAmount") or 0),
            "method": data.get("method") or "", "receipt_url": (data.get("receipt") or {}).get("url") or "",
            "approved_at": data.get("approvedAt"), "cancel_ref": cancels[-1].get("transactionKey", "") if cancels else "",
            "raw": data}


class TossProvider:
    """토스페이먼츠 결제 승인/조회/취소 API (https://docs.tosspayments.com). 실제 인증정보 필요."""
    name = "toss"
    BASE = "https://api.tosspayments.com/v1"

    def __init__(self, secret_key: str, mode: str, client: httpx.Client | None = None):
        self.mode = mode
        token = base64.b64encode(f"{secret_key}:".encode()).decode()
        self.client = client or httpx.Client(timeout=30)
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, json=None, extra=None) -> dict:
        try:
            res = self.client.request(method, self.BASE + path, json=json, headers={**self.headers, **(extra or {})})
        except httpx.HTTPError as exc:
            raise PaymentError("PG_NETWORK_ERROR", f"PG 통신 오류: {exc}") from exc
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            raise PaymentError(data.get("code", f"HTTP_{res.status_code}"), data.get("message", "PG 오류"))
        return data

    def confirm(self, payment_key, order_no, amount):
        return _normalize_toss(self._call("POST", "/payments/confirm",
                                          {"paymentKey": payment_key, "orderId": order_no, "amount": amount},
                                          {"Idempotency-Key": f"confirm-{order_no}"}))

    def fetch(self, payment_key):
        return _normalize_toss(self._call("GET", f"/payments/{payment_key}"))

    def cancel(self, payment_key, amount, reason, idempotency_key):
        body = {"cancelReason": reason or "고객 요청"}
        if amount is not None:
            body["cancelAmount"] = amount
        return _normalize_toss(self._call("POST", f"/payments/{payment_key}/cancel", body,
                                          {"Idempotency-Key": idempotency_key}))


class MockProvider:
    """모의 결제. 실제 금전 거래가 발생하지 않으며 모든 기록에 mode='mock'으로 구분 표시된다."""
    name = "mock"
    mode = "mock"
    ledger: dict[str, dict] = {}

    @classmethod
    def issue(cls, payment_key: str, order_no: str, amount: int, outcome: str = "success") -> None:
        cls.ledger[payment_key] = {"order_no": order_no, "amount": amount, "outcome": outcome, "cancelled": 0}

    def _get(self, payment_key):
        entry = self.ledger.get(payment_key)
        if not entry:
            raise PaymentError("NOT_FOUND_PAYMENT", "존재하지 않는 모의 결제입니다.")
        return entry

    def _view(self, payment_key, entry, status=None):
        balance = entry["amount"] - entry["cancelled"]
        st = status or ("DONE" if entry["cancelled"] == 0 else ("CANCELED" if balance == 0 else "PARTIAL_CANCELED"))
        return {"status": st, "order_no": entry["order_no"], "amount": entry["amount"], "balance": balance,
                "method": "모의결제", "receipt_url": "", "approved_at": None, "cancel_ref": f"mockcancel_{entry['cancelled']}",
                "raw": {"mock": True, "paymentKey": payment_key}}

    def confirm(self, payment_key, order_no, amount):
        entry = self._get(payment_key)
        if entry["outcome"] != "success":
            raise PaymentError("REJECT_CARD_COMPANY", "모의 결제 실패(카드사 거절 시나리오)")
        if entry["order_no"] != order_no:
            raise PaymentError("INVALID_ORDER", "주문번호가 일치하지 않습니다.")
        return self._view(payment_key, entry)

    def fetch(self, payment_key):
        return self._view(payment_key, self._get(payment_key))

    def cancel(self, payment_key, amount, reason, idempotency_key):
        entry = self._get(payment_key)
        amt = entry["amount"] - entry["cancelled"] if amount is None else amount
        if amt > entry["amount"] - entry["cancelled"]:
            raise PaymentError("NOT_CANCELABLE_AMOUNT", "취소 가능 금액을 초과했습니다.")
        entry["cancelled"] += amt
        return self._view(payment_key, entry)


def get_provider(db: Session, mode: str | None = None) -> PaymentProvider:
    state = settings_store.payment_state(db)
    mode = mode or state["mode"]
    if mode == "mock":
        return MockProvider()
    if mode in ("test", "live"):
        secret = settings_store.get(db, "pg.toss.secret_key")
        if not secret:
            raise PaymentError("PG_NOT_CONFIGURED", "PG 인증정보가 등록되지 않았습니다.")
        return TossProvider(secret, mode)
    raise PaymentError("PG_DISABLED", "결제가 비활성화되어 있습니다.")
