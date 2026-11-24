"""보안·배포: 권한 없는 접근 차단·고객별 데이터 격리·관리자 인증·API 인증·헬스체크·백업/복구."""
import uuid

from sqlalchemy import func, select

from conftest import ADMIN_PW, Cust, login

ADMIN_GETS = ["dashboard", "customers", "users", "roles", "apps", "orders", "products", "coupons", "payments", "refunds",
              "revenue", "pg", "payment-events", "agents", "agent-downloads", "devices", "device-groups", "incidents",
              "commands", "jobs", "plans", "scenarios", "live", "results", "crashes", "screenshots", "reports", "tickets",
              "announcements", "faqs", "legal", "settings", "emails", "status", "audit-logs", "system-logs", "backups",
              "notification-templates", "files/quarantine"]


def test_health_and_public_pages(client):
    assert client.get("/api/health").json()["status"] == "ok"
    site = client.get("/api/public/site").json()
    assert "Google의 공식 서비스가 아닌" in site["notice"]
    for key in ("terms", "privacy", "refund"):
        assert client.get(f"/api/public/legal/{key}").status_code == 200
    assert client.get("/api/public/faqs").json()
    assert client.get("/api/nope").status_code == 404
    res = client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff" and res.headers["x-frame-options"] == "DENY"


def test_every_admin_menu_requires_admin(client, customer, admin):
    for path in ADMIN_GETS:
        url = f"/api/admin/{path}"
        assert client.get(url).status_code == 401, path                       # 비로그인
        assert client.get(url, headers=customer.h).status_code == 403, path   # 일반 고객
        assert client.get(url, headers=admin).status_code == 200, path        # 관리자: 실제 DB 응답
    assert client.get("/api/admin/dashboard", headers={"Authorization": "Bearer forged.token.value"}).status_code == 401


def test_role_based_menu_permissions(client, admin):
    def staff(role):
        name = f"st{uuid.uuid4().hex[:8]}"
        r = client.post("/api/admin/users", headers=admin, json={"email": f"{name}@example.com", "username": name, "name": role,
                                                                  "password": "Staff-pass-1", "role": role})
        assert r.status_code == 200, r.text
        s = login(client, name, "Staff-pass-1")
        assert s["user"]["must_change_password"] is True                       # 초기 비밀번호 변경 요구
        return {"Authorization": "Bearer " + s["access_token"]}

    billing, support, operator = staff("billing"), staff("support"), staff("operator")
    assert client.get("/api/admin/payments", headers=billing).status_code == 200
    assert client.get("/api/admin/devices", headers=billing).status_code == 403
    assert client.get("/api/admin/settings", headers=billing).status_code == 403
    assert client.get("/api/admin/tickets", headers=support).status_code == 200
    assert client.get("/api/admin/payments", headers=support).status_code == 403
    assert client.put("/api/admin/pg", headers=support, json={"mode": "mock"}).status_code == 403
    assert client.get("/api/admin/devices", headers=operator).status_code == 200
    assert client.get("/api/admin/users", headers=operator).status_code == 403
    assert client.post("/api/admin/users", headers=operator, json={"email": "x@example.com", "username": "xxxx", "name": "x",
                                                                    "password": "Staff-pass-1", "role": "superadmin"}).status_code == 403


def test_tenant_isolation(client, admin, mock_pg, farm, db):
    """고객 A의 앱·주문·검사 결과·보고서·문의에 고객 B가 접근할 수 없다."""
    from app.models import Report, TestPlan
    from app.services import scheduler
    a, b = Cust(client), Cust(client)
    app, version = a.make_app()
    order = a.order(app, version)
    a.pay(order)
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))
    scheduler.tick_schedules(db)
    farm.cycle()
    rep = client.post(f"/api/plans/{plan.id}/reports", headers=a.h, json={"kind": "comprehensive", "fmt": "pdf"}).json()
    ticket = client.post("/api/tickets", headers=a.h, json={"subject": "s", "body": "b"}).json()
    sc = client.post("/api/scenarios", headers=a.h, json={"name": "s", "steps": [{"action": "launch"}]}).json()
    denied = [
        client.get(f"/api/apps/{app['id']}", headers=b.h), client.put(f"/api/apps/{app['id']}", headers=b.h, json={"name": "x", "package_name": app["package_name"]}),
        client.delete(f"/api/apps/{app['id']}", headers=b.h), client.get(f"/api/orders/{order['id']}", headers=b.h),
        client.post(f"/api/orders/{order['id']}/cancel", headers=b.h), client.get(f"/api/plans/{plan.id}", headers=b.h),
        client.get(f"/api/plans/{plan.id}/results", headers=b.h), client.get(f"/api/plans/{plan.id}/crashes", headers=b.h),
        client.get(f"/api/plans/{plan.id}/screenshots", headers=b.h), client.post(f"/api/plans/{plan.id}/reports", headers=b.h, json={"kind": "daily"}),
        client.get(f"/api/reports/{rep['id']}/download", headers=b.h), client.get(f"/api/tickets/{ticket['id']}", headers=b.h),
        client.post(f"/api/tickets/{ticket['id']}/messages", headers=b.h, json={"body": "x"}),
        client.put(f"/api/scenarios/{sc['id']}", headers=b.h, json={"name": "x", "steps": [{"action": "launch"}]}),
        client.get(f"/api/apps/{app['id']}/closed-test", headers=b.h), client.get(f"/api/apps/{app['id']}/testers.csv", headers=b.h),
        client.post("/api/orders", headers=b.h, json={"app_id": app["id"], "app_version_id": version["id"], "product_id": 1}),
        client.post("/api/payments/prepare", headers=b.h, json={"order_id": order["id"]}),
    ]
    assert [r.status_code for r in denied] == [404] * len(denied)
    assert client.get("/api/apps", headers=b.h).json() == [] and client.get("/api/orders", headers=b.h).json() == []
    assert client.get("/api/reports", headers=b.h).json()["items"] == [] and client.get("/api/payments", headers=b.h).json() == []
    assert client.get("/api/dashboard", headers=b.h).json()["runs_total"] == 0
    assert client.get(f"/api/reports/{rep['id']}/download", headers=a.h).status_code == 200
    assert db.get(Report, rep["id"]).customer_id == plan.customer_id
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_scenario_versioning_and_validation(client, customer):
    bad = client.post("/api/scenarios", headers=customer.h, json={"name": "x", "steps": [{"action": "shell", "text": "rm -rf"}]})
    assert bad.status_code == 400
    no_sel = client.post("/api/scenarios", headers=customer.h, json={"name": "x", "steps": [{"action": "input", "text": "a"}]})
    assert no_sel.status_code == 400                                              # UI 요소 식별자 필수
    s1 = client.post("/api/scenarios", headers=customer.h, json={"name": "로그인", "steps": [
        {"action": "launch"}, {"action": "tap", "selector": {"resource_id": "login_button"}, "expected": "로그인 화면"}]}).json()
    s2 = client.put(f"/api/scenarios/{s1['id']}", headers=customer.h, json={"name": "로그인 v2", "steps": [{"action": "launch"}]}).json()
    assert (s1["version"], s2["version"]) == (1, 2) and s2["root_id"] == s1["id"]
    history = client.get(f"/api/scenarios/{s2['id']}/versions", headers=customer.h).json()
    assert [h["version"] for h in history] == [2, 1]


def test_closed_test_separates_human_testers_from_device_runs(client, customer):
    app, _ = customer.make_app()
    aid = app["id"]
    added = client.post(f"/api/apps/{aid}/testers", headers=customer.h, json={"emails": ["a@example.com", "b@example.com", "bad", "a@example.com"]})
    assert added.json()["added"] == 2
    data = client.get(f"/api/apps/{aid}/closed-test", headers=customer.h).json()
    assert data["human_testers_invited"] == 2 and data["human_testers_joined"] == 0 and data["real_devices_tested"] == 0
    tid = data["testers"][0]["id"]
    client.patch(f"/api/apps/{aid}/testers/{tid}", headers=customer.h, json={"status": "confirmed", "feedback": "버튼이 작아요"})
    data = client.get(f"/api/apps/{aid}/closed-test", headers=customer.h).json()
    assert data["human_testers_confirmed"] == 1 and "인간 테스터 참여로 집계되지 않습니다" in data["notice"]
    csv = client.get(f"/api/apps/{aid}/testers.csv", headers=customer.h)
    assert csv.text.split() == ["a@example.com", "b@example.com"]
    notes = client.get(f"/api/apps/{aid}/production-notes", headers=customer.h).json()["text"]
    assert "버튼이 작아요" in notes and "보장" not in notes.replace("승인 보장", "")


def test_admin_crud_audit_and_settings_masking(client, admin, db):
    from app.models import AuditLog, SystemSetting
    p = client.post("/api/admin/products", headers=admin, json={"code": "T" + uuid.uuid4().hex[:6], "name": "임시", "price": 1000,
                                                                 "duration_days": 3, "device_count": 2, "daily_runs": 1, "checks": ["install"]}).json()
    assert client.put(f"/api/admin/products/{p['id']}", headers=admin, json={"price": 2000, "is_active": False}).json()["price"] == 2000
    assert client.put(f"/api/admin/products/{p['id']}", headers=admin, json={"id": 999}).status_code == 400
    assert p["code"] not in [x["code"] for x in client.get("/api/public/products").json()]          # 판매 비활성화 반영
    assert client.delete(f"/api/admin/products/{p['id']}", headers=admin).status_code == 200
    assert client.put("/api/admin/settings", headers=admin, json={"smtp.password": "s3cret-value", "ai.api_key": "sk-abc12345"}).status_code == 200
    view = {s["key"]: s for s in client.get("/api/admin/settings", headers=admin).json()}
    assert view["smtp.password"]["value"] == "" and view["smtp.password"]["is_set"] and view["ai.api_key"]["hint"] == "sk-a****"
    stored = db.get(SystemSetting, "smtp.password").value
    assert "s3cret-value" not in stored and stored.startswith("gAAAA")                               # 암호화 저장
    assert client.put("/api/admin/settings", headers=admin, json={"pg.mode": "live"}).status_code == 400
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.in_(["products.update", "settings.update"]))) >= 2
    client.put("/api/admin/settings", headers=admin, json={"ai.provider": "none"})
    assert client.post("/api/admin/settings/test-ai", headers=admin).json()["ok"] is False
    assert client.post("/api/admin/settings/test-email", headers=admin, json={"to": "a@example.com"}).json()["ok"] is False
    assert client.post("/api/admin/pg/test", headers=admin).json()["ok"] is False


def test_xss_payload_is_stored_as_data_and_sqli_is_inert(client, customer):
    payload = "<script>alert(1)</script>' OR '1'='1"
    t = client.post("/api/tickets", headers=customer.h, json={"subject": payload, "body": payload}).json()
    got = client.get(f"/api/tickets/{t['id']}", headers=customer.h)
    assert got.json()["subject"] == payload and got.headers["content-type"].startswith("application/json")
    assert client.post("/api/auth/login", json={"identifier": "admin' OR '1'='1' --", "password": "x"}).status_code == 401
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]


def test_backup_and_restore_roundtrip(client, admin, db):
    """백업 → 데이터 변경 → 복구 → 백업 시점 데이터로 복원."""
    from app.models import Announcement
    keep = client.post("/api/admin/announcements", headers=admin, json={"title": "백업 전 공지", "body": "유지"}).json()
    backup = client.post("/api/admin/backups", headers=admin).json()
    assert backup["size"] > 0 and client.get(f"/api/admin/backups/{backup['id']}/download", headers=admin).content[:2] == b"\x1f\x8b"
    lost = client.post("/api/admin/announcements", headers=admin, json={"title": "백업 후 공지", "body": "사라짐"}).json()
    client.delete(f"/api/admin/announcements/{keep['id']}", headers=admin)
    assert client.post(f"/api/admin/backups/{backup['id']}/restore", headers=admin, json={"confirm": "nope"}).status_code == 400
    res = client.post(f"/api/admin/backups/{backup['id']}/restore", headers=admin, json={"confirm": "RESTORE"})
    assert res.status_code == 200 and res.json()["rows"] > 100
    db.expire_all()
    titles = set(db.scalars(select(Announcement.title)))
    assert "백업 전 공지" in titles and "백업 후 공지" not in titles and lost
    fresh = login(client, "admin", ADMIN_PW)                                   # 복구 후에도 로그인·신규 등록(시퀀스) 정상
    h = {"Authorization": "Bearer " + fresh["access_token"]}
    assert client.post("/api/admin/announcements", headers=h, json={"title": "복구 후 공지"}).status_code == 200
    kinds = [b["kind"] for b in client.get("/api/admin/backups", headers=h).json()]
    assert "restore" in kinds and "pre_restore" in kinds
