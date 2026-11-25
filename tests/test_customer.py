"""고객 기능: 회원가입·로그인·로그아웃·비밀번호 재설정·앱 등록·파일 업로드·상품·주문."""
import re
import uuid

from sqlalchemy import select

from conftest import Cust, login, make_apk


def test_register_login_logout_refresh(client, db):
    c = Cust(client)
    me = client.get("/api/me", headers=c.h).json()
    assert me["email"] == c.email and me["role"] == "customer" and not me["is_staff"]
    assert client.post("/api/auth/register", json={"email": c.email, "password": "Passw0rd-123", "name": "x", "agree_terms": True}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "weak@example.com", "password": "short", "name": "x", "agree_terms": True}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "no@example.com", "password": "Passw0rd-123", "name": "x", "agree_terms": False}).status_code == 400
    session = login(client, c.email, c.password)
    rotated = client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert rotated.status_code == 200
    # 회전된 갱신 토큰은 짧은 유예(60초) 뒤에는 재사용할 수 없다
    assert client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 200
    from datetime import timedelta
    from app.db import utcnow
    from app.models import Session as UserSession
    from app.security import sha256_hex
    db.execute(UserSession.__table__.update().where(UserSession.refresh_hash == sha256_hex(session["refresh_token"]))
               .values(rotated_at=utcnow() - timedelta(minutes=2)))
    db.commit()
    assert client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401
    new_refresh = rotated.json()["refresh_token"]
    assert client.post("/api/auth/logout", json={"refresh_token": new_refresh}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_email_verification_and_password_reset(client, db):
    from app.models import Notification, User
    c = Cust(client)
    user = db.scalar(select(User).where(User.email == c.email))
    mail = db.scalar(select(Notification).where(Notification.user_id == user.id, Notification.event == "verify_email"))
    assert mail.channel == "email" and mail.status == "queued"
    token = re.search(r"token=([\w\-]+)", mail.body).group(1)
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400  # 1회용
    assert client.get("/api/me", headers=c.h).json()["email_verified"] is True

    assert client.post("/api/auth/forgot", json={"email": c.email}).status_code == 200
    assert client.post("/api/auth/forgot", json={"email": "nobody@example.com"}).status_code == 200  # 가입 여부 비노출
    db.expire_all()
    mail = db.scalar(select(Notification).where(Notification.user_id == user.id, Notification.event == "reset_password"))
    token = re.search(r"token=([\w\-]+)", mail.body).group(1)
    assert client.post("/api/auth/reset", json={"token": token, "password": "New-passw0rd-9"}).status_code == 200
    assert client.post("/api/auth/login", json={"identifier": c.email, "password": c.password}).status_code == 401
    login(client, c.email, "New-passw0rd-9")
    # 재설정 시 기존 세션(갱신 토큰)은 모두 폐기된다
    assert client.post("/api/auth/refresh", json={"refresh_token": c.session["refresh_token"]}).status_code == 401


def test_email_queue_marks_not_sent_without_smtp(client, db):
    """SMTP 미설정 시 실제 발송하지 않았음을 명확히 구분한다. 설정 시에는 재시도 로직이 동작한다."""
    from app.models import Notification
    from app.services import notifications
    Cust(client)
    stats = notifications.process_email_queue(db, limit=1000)
    assert stats["sent"] == 0 and stats["not_sent_no_smtp"] > 0
    assert not db.scalar(select(Notification.id).where(Notification.channel == "email", Notification.status == "sent"))
    # SMTP 설정 후: 발송 실패 → 재시도 예약, 성공 → sent
    from app.services import settings_store
    settings_store.put(db, "smtp.host", "smtp.invalid")
    settings_store.put(db, "smtp.from", "noreply@example.com")
    db.commit()
    try:
        c = Cust(client)
        calls = []

        def flaky(_db, to, subject, body):
            calls.append(to)
            if len(calls) == 1:
                raise OSError("connection refused")

        s1 = notifications.process_email_queue(db, limit=1, sender=flaky)
        assert s1["sent"] == 0
        row = db.scalar(select(Notification).where(Notification.channel == "email", Notification.attempts == 1))
        assert row.status == "queued" and row.last_error and row.next_attempt_at > row.created_at
        s2 = notifications.process_email_queue(db, limit=1000, sender=lambda *a: None)
        assert s2["sent"] >= 1 and c.email
    finally:
        settings_store.put(db, "smtp.host", "")
        db.commit()


def test_account_lock_after_failed_logins(client):
    c = Cust(client)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"identifier": c.email, "password": "wrong-pass-1"}).status_code == 401
    assert client.post("/api/auth/login", json={"identifier": c.email, "password": c.password}).status_code == 423
    logins = client.get("/api/me/logins", headers=c.h).json()
    assert sum(1 for l in logins if not l["success"]) >= 5


def test_app_registration_and_validation(client, customer):
    h = customer.h
    assert client.post("/api/apps", headers=h, json={"name": "a", "package_name": "not a package", "ownership_confirmed": True}).status_code == 400
    assert client.post("/api/apps", headers=h, json={"name": "a", "package_name": "com.ok.app", "ownership_confirmed": False}).status_code == 400
    pkg = f"com.test.v{uuid.uuid4().hex[:8]}"
    app = client.post("/api/apps", headers=h, json={"name": "내 앱", "package_name": pkg, "ownership_confirmed": True,
                                                     "play_url": "https://play.google.com/store/apps/details?id=" + pkg,
                                                     "test_login_id": "tester", "test_login_password": "secret-pw"}).json()
    assert app["has_test_login"] and "test_login_password" not in app
    assert client.post("/api/apps", headers=h, json={"name": "dup", "package_name": pkg, "ownership_confirmed": True}).status_code == 409
    assert client.post("/api/apps", headers=h, json={"name": "a", "package_name": "com.x.y", "ownership_confirmed": True,
                                                     "play_url": "javascript:alert(1)"}).status_code == 400


def test_apk_upload_hash_duplicate_and_quarantine(client, customer, db):
    from app.models import AppFile
    app, version = customer.make_app()
    pkg = app["package_name"]
    assert version["file"]["status"] == "clean" and len(version["file"]["sha256"]) == 64
    up = lambda name, data, code: client.post(f"/api/apps/{app['id']}/versions", headers=customer.h,  # noqa: E731
                                              data={"version_name": "x", "version_code": str(code)},
                                              files={"file": (name, data, "application/octet-stream")})
    assert up("a.txt", b"hello", 2).status_code == 400                       # 확장자
    r = up("fake.apk", b"this is not a zip", 3)                              # 형식 위반 → 격리
    assert r.status_code == 422 and "격리" in r.json()["detail"]
    assert up("nodex.apk", make_apk(pkg, 4, dex=False), 4).status_code == 422  # 실행 코드 없음 → 격리
    assert up("other.apk", make_apk("com.other.pkg", 5), 5).status_code == 422  # 패키지명 불일치 → 격리
    quarantined = db.scalars(select(AppFile).where(AppFile.app_id == app["id"], AppFile.status == "quarantined")).all()
    assert len(quarantined) == 3 and all(q.path.startswith("quarantine/") for q in quarantined)
    same = make_apk(pkg, 6)
    assert up("v6.apk", same, 6).status_code == 200
    assert up("v6-again.apk", same, 7).status_code == 409                    # 동일 해시 중복
    assert up("v6.apk", make_apk(pkg, 6), 6).status_code == 409              # 버전 코드 중복
    versions = client.get(f"/api/apps/{app['id']}", headers=customer.h).json()["versions"]
    assert [v["version_code"] for v in versions] == [6, 1, 0]                # 버전 이력(0 = Play 스토어 배포본)


def test_products_orders_and_coupon(client, customer, admin):
    products = client.get("/api/public/products").json()
    assert [p["code"] for p in products][:4] == ["BASIC", "STANDARD", "PRO", "PREMIUM"]
    assert {p["code"]: p["price"] for p in products}["PRO"] == 14900
    app, version = customer.make_app()
    code = "T" + uuid.uuid4().hex[:8].upper()
    assert client.post("/api/admin/coupons", headers=admin, json={"code": code, "kind": "percent", "value": 10, "max_uses": 1}).status_code == 200
    order = customer.order(app, version, "STANDARD", coupon_code=code)
    assert order["amount"] == 9900 and order["discount"] == 990 and order["final_amount"] == 8910
    assert order["status"] == "pending_payment" and order["order_no"].startswith("GAT")
    listed = client.get("/api/orders", headers=customer.h).json()
    assert [o["id"] for o in listed] == [order["id"]]
    ent = next(p for p in products if p["code"] == "ENTERPRISE")
    assert client.post("/api/orders", headers=customer.h, json={"app_id": app["id"], "app_version_id": version["id"], "product_id": ent["id"]}).status_code == 400
    # 멱등 키: 같은 요청은 같은 주문을 돌려준다
    body = {"app_id": app["id"], "app_version_id": version["id"], "product_id": products[0]["id"]}
    key = uuid.uuid4().hex
    a = client.post("/api/orders", headers={**customer.h, "Idempotency-Key": key}, json=body).json()
    b = client.post("/api/orders", headers={**customer.h, "Idempotency-Key": key}, json=body).json()
    assert a["id"] == b["id"]
    assert client.post(f"/api/orders/{a['id']}/cancel", headers=customer.h).status_code == 200


def test_support_ticket_and_notifications(client, customer, admin):
    t = client.post("/api/tickets", headers=customer.h, json={"subject": "문의드립니다", "body": "검사 기간 문의"}).json()
    assert client.post(f"/api/admin/tickets/{t['id']}/reply", headers=admin, json={"body": "답변입니다."}).status_code == 200
    got = client.get(f"/api/tickets/{t['id']}", headers=customer.h).json()
    assert got["status"] == "answered" and [m["is_staff"] for m in got["messages"]] == [False, True]
    notes = client.get("/api/notifications", headers=customer.h).json()
    assert any(n["event"] == "ticket_answered" for n in notes["items"]) and notes["unread"] > 0
    client.post("/api/notifications/read", headers=customer.h)
    assert client.get("/api/notifications", headers=customer.h).json()["unread"] == 0


def test_withdraw_anonymizes_account(client):
    c = Cust(client)
    assert client.post("/api/me/withdraw", headers=c.h, json={"password": "wrong"}).status_code == 400
    assert client.post("/api/me/withdraw", headers=c.h, json={"password": c.password}).status_code == 200
    assert client.get("/api/me", headers=c.h).status_code == 401
    assert client.post("/api/auth/login", json={"identifier": c.email, "password": c.password}).status_code == 401


def test_playstore_listing_parser_and_fetch():
    """스토어 페이지 해석: 제목 접미사 제거, 허용 호스트의 아이콘만 채택, 없는 앱은 found=False."""
    import httpx
    from app.services import playstore
    page = ('<html><head><meta property="og:title" content="내 앱 &amp; 친구 - Google Play 앱">'
            '<meta property="og:image" content="https://play-lh.googleusercontent.com/abc123">'
            '<meta property="og:description" content="설명입니다"></head></html>')

    def handler(request):
        if request.url.host == "play.google.com":
            assert request.url.params["id"] in ("com.real.app", "com.none.app")
            return httpx.Response(200, text=page) if request.url.params["id"] == "com.real.app" else httpx.Response(404)
        return httpx.Response(200, content=b"\x89PNG....")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    info = playstore.fetch_listing("com.real.app", client=client)
    assert info == {"found": True, "name": "내 앱 & 친구", "icon": "https://play-lh.googleusercontent.com/abc123",
                    "description": "설명입니다", "play_url": "https://play.google.com/store/apps/details?id=com.real.app"}
    assert playstore.fetch_listing("com.none.app", client=client) == {"found": False}
    evil = page.replace("https://play-lh.googleusercontent.com/abc123", "http://169.254.169.254/latest")
    assert playstore.parse_listing(evil, "com.real.app")["icon"] == ""          # 허용 호스트 외 주소는 버린다
    assert playstore.fetch_icon("http://169.254.169.254/latest", client=client) is None


def test_register_app_with_package_name_only(client, customer, monkeypatch):
    """패키지명만으로 등록: 스토어에서 이름·주소·아이콘을 불러온다. 조회되지 않으면 이름 입력을 요구한다."""
    from app.services import playstore
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    found = {"found": True, "name": "스토어 앱 이름", "icon": "https://play-lh.googleusercontent.com/x", "description": "스토어 설명",
             "play_url": "https://play.google.com/store/apps/details?id=PKG"}
    monkeypatch.setattr(playstore, "fetch_listing", lambda pkg, *a, **k: {**found, "play_url": found["play_url"].replace("PKG", pkg)} if "pub" in pkg else {"found": False})
    monkeypatch.setattr(playstore, "fetch_icon", lambda url, *a, **k: png)
    pkg = f"com.pub.a{uuid.uuid4().hex[:8]}"
    look = client.post("/api/apps/lookup", headers=customer.h, json={"package_name": pkg}).json()
    assert look["found"] and look["name"] == "스토어 앱 이름" and look["registered"] is False
    assert client.post("/api/apps/lookup", headers=customer.h, json={"package_name": "bad name"}).status_code == 400
    app = client.post("/api/apps", headers=customer.h, json={"package_name": pkg, "ownership_confirmed": True}).json()
    assert app["name"] == "스토어 앱 이름" and app["play_url"].endswith(pkg) and app["description"] == "스토어 설명"
    assert client.get(app["icon_url"]).content == png
    assert client.post("/api/apps/lookup", headers=customer.h, json={"package_name": pkg}).json()["registered"] is True
    hidden = f"com.closed.a{uuid.uuid4().hex[:8]}"
    r = client.post("/api/apps", headers=customer.h, json={"package_name": hidden, "ownership_confirmed": True})
    assert r.status_code == 400 and "앱 이름을 직접 입력" in r.json()["detail"]
    ok = client.post("/api/apps", headers=customer.h, json={"package_name": hidden, "name": "직접 입력", "ownership_confirmed": True})
    assert ok.status_code == 200 and ok.json()["name"] == "직접 입력"


def test_play_link_registration_and_tester_accounts(client, customer, admin, monkeypatch, db):
    """Play Store 링크로 등록 → 기본 'Play 스토어 배포본' 버전 생성. 검사 기기 계정 목록은 실기기만 제공한다."""
    from app.models import Agent, Device
    from app.services import playstore
    monkeypatch.setattr(playstore, "fetch_listing", lambda pkg, *a, **k: {"found": True, "name": "링크 앱", "icon": "", "description": "", "play_url": "https://play.google.com/store/apps/details?id=" + pkg})
    pkg = f"com.link.a{uuid.uuid4().hex[:8]}"
    link = f"https://play.google.com/store/apps/details?id={pkg}&hl=ko"
    assert client.post("/api/apps/lookup", headers=customer.h, json={"package_name": link}).json()["package_name"] == pkg
    app = client.post("/api/apps", headers=customer.h, json={"package_name": link, "ownership_confirmed": True}).json()
    assert app["package_name"] == pkg and [v["version_name"] for v in app["versions"]] == ["Play 스토어 배포본"]
    order = customer.order(app, app["versions"][0])                         # APK 없이 바로 신청 가능
    assert order["status"] == "pending_payment"
    agent = Agent(uid="AG-" + uuid.uuid4().hex[:8], name="real-farm", kind="real", status="online")
    db.add(agent)
    db.flush()
    real = Device(agent_id=agent.id, serial="R1" + uuid.uuid4().hex[:6], is_mock=False, enabled=False)
    mock = Device(agent_id=agent.id, serial="M1" + uuid.uuid4().hex[:6], is_mock=True, google_account_email="mock@example.com")
    db.add_all([real, mock])
    db.commit()
    mail = f"farm-{uuid.uuid4().hex[:6]}@gmail.com"
    assert client.patch(f"/api/admin/devices/{real.id}", headers=admin, json={"google_account_email": "not-an-email"}).status_code == 400
    r = client.patch(f"/api/admin/devices/{real.id}", headers=admin, json={"google_account_email": mail.upper(), "enabled": True})
    assert r.json()["google_account_email"] == mail
    got = client.get("/api/tester-accounts", headers=customer.h).json()
    assert mail in got["emails"] and "mock@example.com" not in got["emails"] and "사람 테스터가 아닙니다" in got["notice"]
    assert client.get("/api/tester-accounts").status_code == 401
    client.patch(f"/api/admin/devices/{real.id}", headers=admin, json={"enabled": False})
