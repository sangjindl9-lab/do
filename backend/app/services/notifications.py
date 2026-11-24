"""웹 알림 + 이메일 발송 대기열. SMTP 미설정 시 실제 발송하지 않고 'not_sent_no_smtp'로 명확히 구분한다."""
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Notification, NotificationTemplate, Role, User
from . import settings_store

# event: (ko 제목, ko 본문, en 제목, en 본문)
TEMPLATES = {
    "signup": ("회원가입을 환영합니다", "{name}님, 구글자동테스터 가입이 완료되었습니다.",
               "Welcome", "Hi {name}, your Google Auto Tester account is ready."),
    "verify_email": ("이메일 인증 안내", "아래 링크에서 이메일 인증을 완료해 주세요.\n{link}",
                     "Verify your email", "Please verify your email:\n{link}"),
    "reset_password": ("비밀번호 재설정 안내", "아래 링크에서 비밀번호를 재설정해 주세요. (1시간 유효)\n{link}",
                       "Reset your password", "Reset your password (valid for 1 hour):\n{link}"),
    "order_received": ("주문이 접수되었습니다", "주문번호 {order_no} ({app}) 접수가 완료되었습니다.",
                       "Order received", "Order {order_no} ({app}) has been received."),
    "payment_done": ("결제가 완료되었습니다", "주문번호 {order_no} 결제({amount}원)가 완료되었습니다.",
                     "Payment completed", "Payment of KRW {amount} for order {order_no} is complete."),
    "payment_failed": ("결제에 실패했습니다", "주문번호 {order_no} 결제가 실패했습니다. 사유: {reason}",
                       "Payment failed", "Payment for order {order_no} failed: {reason}"),
    "devices_assigned": ("검사 기기가 배정되었습니다", "주문번호 {order_no}에 검사 기기 {count}대가 배정되었습니다.",
                         "Devices assigned", "{count} test devices were assigned to order {order_no}."),
    "test_started": ("검사가 시작되었습니다", "{app} 검사가 시작되었습니다. 종료 예정일: {end}",
                     "Testing started", "Testing of {app} has started. Ends on {end}."),
    "test_error": ("검사 중 오류가 발생했습니다", "{app} 검사 작업에서 오류가 발생했습니다: {reason}",
                   "Test error", "An error occurred while testing {app}: {reason}"),
    "crash_found": ("크래시가 발견되었습니다", "{app}에서 {kind}이(가) 발견되었습니다: {title}",
                    "Crash detected", "{kind} detected in {app}: {title}"),
    "device_disconnected": ("장비 연결이 끊어졌습니다", "{target} 연결이 끊어졌습니다.",
                            "Device disconnected", "{target} has been disconnected."),
    "test_delayed": ("검사가 지연되고 있습니다", "주문번호 {order_no}: {reason}",
                     "Testing delayed", "Order {order_no}: {reason}"),
    "test_ending": ("검사 종료 예정 안내", "{app} 검사가 {end}에 종료될 예정입니다.",
                    "Testing ends soon", "Testing of {app} ends on {end}."),
    "test_completed": ("검사가 완료되었습니다", "{app} 검사 기간이 종료되었습니다.",
                       "Testing completed", "The test period for {app} has finished."),
    "report_issued": ("보고서가 발행되었습니다", "{app} 보고서({report_no})가 발행되었습니다.",
                      "Report issued", "Report {report_no} for {app} is available."),
    "refund_done": ("환불이 완료되었습니다", "주문번호 {order_no} 환불({amount}원)이 완료되었습니다.",
                    "Refund completed", "A refund of KRW {amount} for order {order_no} is complete."),
    "ticket_answered": ("문의에 답변이 등록되었습니다", "문의 '{subject}'에 답변이 등록되었습니다.",
                        "Support reply", "Your inquiry '{subject}' has a new reply."),
}


class _Safe(dict):
    def __missing__(self, key):
        return ""


def seed_templates(db: Session) -> None:
    existing = {(t.event, t.locale) for t in db.scalars(select(NotificationTemplate))}
    for event, (ks, kb, es, eb) in TEMPLATES.items():
        if (event, "ko") not in existing:
            db.add(NotificationTemplate(event=event, locale="ko", subject=ks, body=kb))
        if (event, "en") not in existing:
            db.add(NotificationTemplate(event=event, locale="en", subject=es, body=eb))


def notify(db: Session, user_id: int, event: str, ctx: dict | None = None, link: str = "",
           web: bool = True, email: bool = True) -> None:
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return
    locale = user.locale if user.locale in ("ko", "en") else "ko"
    tpl = db.scalar(select(NotificationTemplate).where(NotificationTemplate.event == event,
                                                       NotificationTemplate.locale == locale))
    if tpl is None:
        ks, kb, es, eb = TEMPLATES.get(event, (event, "", event, ""))
        subject, body = (ks, kb) if locale == "ko" else (es, eb)
    else:
        subject, body = tpl.subject, tpl.body
    data = _Safe(ctx or {})
    data.setdefault("name", user.name or user.email)
    title, text = subject.format_map(data), body.format_map(data)
    if web:
        db.add(Notification(user_id=user_id, event=event, channel="web", title=title, body=text, link=link,
                            status="unread"))
    if email:
        db.add(Notification(user_id=user_id, event=event, channel="email", title=title, body=text, link=link,
                            status="queued", next_attempt_at=utcnow()))


def notify_staff(db: Session, event: str, ctx: dict | None = None, link: str = "") -> None:
    staff = db.scalars(select(User).join(Role).where(Role.is_staff.is_(True), User.is_active.is_(True)))
    for user in staff:
        if user.role.code in ("superadmin", "operator"):
            notify(db, user.id, event, ctx, link)


def _send(db: Session, to_addr: str, subject: str, body: str) -> None:
    host, port = settings_store.get(db, "smtp.host"), settings_store.get_int(db, "smtp.port")
    user, password = settings_store.get(db, "smtp.user"), settings_store.get(db, "smtp.password")
    tls = settings_store.get(db, "smtp.tls")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings_store.get(db, "smtp.from"), to_addr, subject
    msg.set_content(body)
    if tls == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=20)
    with server:
        if tls == "starttls":
            server.starttls(context=ssl.create_default_context())
        if user:
            server.login(user, password)
        server.send_message(msg)


def process_email_queue(db: Session, limit: int = 30, sender=None) -> dict:
    """발송 대기열 처리. 실패 시 지수 백오프로 최대 5회 재시도."""
    stats = {"sent": 0, "failed": 0, "not_sent_no_smtp": 0}
    rows = db.scalars(select(Notification).where(
        Notification.channel == "email", Notification.status == "queued",
        Notification.next_attempt_at <= utcnow()).limit(limit).with_for_update(of=Notification, skip_locked=True)).all()
    configured = settings_store.smtp_configured(db)
    for row in rows:
        if not configured:
            row.status, row.last_error = "not_sent_no_smtp", "SMTP 미설정으로 발송되지 않음"
            stats["not_sent_no_smtp"] += 1
            continue
        user = db.get(User, row.user_id)
        row.attempts += 1
        try:
            body = row.body + (f"\n\n{row.link}" if row.link.startswith("http") else "")
            (sender or _send)(db, user.email, row.title, body)
            row.status, row.sent_at = "sent", utcnow()
            stats["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - 발송 오류는 기록 후 재시도
            row.last_error = str(exc)[:300]
            if row.attempts >= 5:
                row.status = "failed"
                stats["failed"] += 1
            else:
                row.next_attempt_at = utcnow() + timedelta(minutes=2 ** row.attempts)
    db.commit()
    return stats
