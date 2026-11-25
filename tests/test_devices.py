"""장비: 에이전트 인증·모의 기기 등록·상태 갱신·자동 배정·연결 끊김 감지·재연결·작업 수신·결과 저장·원격 제어."""
from datetime import timedelta

from sqlalchemy import func, select

from conftest import Farm
from test_payment import retire_all


def test_agent_enroll_and_token_lifecycle(client, admin, db):
    from gat_agent.api import ApiError, ServerClient
    from gat_agent.core import rotate_token
    farm = Farm(client, admin, count=2)
    # 등록 코드는 1회용
    assert client.post("/api/agent/enroll", json={"code": farm.info["enroll_code"]}).status_code == 401
    assert client.post("/api/agent/heartbeat", json={"devices": []}).status_code == 401                      # 인증키 없음
    assert client.post("/api/agent/heartbeat", json={"devices": []}, headers={"X-Agent-Token": "bogus"}).status_code == 401
    old = farm.cfg.token
    rotate_token(farm.cfg, farm.api)                                                                        # 인증키 갱신
    assert farm.cfg.token != old
    assert client.post("/api/agent/heartbeat", json={"devices": []}, headers={"X-Agent-Token": old}).status_code == 401
    farm.api.token = farm.cfg.token
    farm.cycle()
    assert client.post(f"/api/admin/agents/{farm.info['id']}/revoke", headers=admin).status_code == 200      # 인증키 폐기
    try:
        ServerClient("http://testserver", farm.cfg.token, client=client).heartbeat("1", [], [])
        raise AssertionError("revoked token must fail")
    except ApiError as exc:
        assert exc.status == 401


def test_admin_token_cannot_be_used_as_agent_and_vice_versa(client, admin, farm):
    assert client.post("/api/agent/heartbeat", json={"devices": []}, headers=admin).status_code == 401
    assert client.get("/api/admin/devices", headers={"Authorization": "Bearer " + farm.cfg.token}).status_code == 401
    assert client.get("/api/admin/devices", headers={"X-Agent-Token": farm.cfg.token}).status_code == 401


def test_mock_devices_register_and_update_status(client, admin, farm, db):
    from app.models import Device, DeviceHeartbeat
    devs = db.scalars(select(Device).where(Device.agent_id == farm.info["id"]).order_by(Device.serial)).all()
    assert len(devs) == 6 and all(d.is_mock and d.status == "idle" and d.conn_state == "device" for d in devs)
    assert devs[0].model == "Mock S20" and devs[0].resolution == "1080x2400" and devs[0].ram_mb == 8192
    assert db.scalar(select(func.count()).select_from(DeviceHeartbeat).where(DeviceHeartbeat.device_id == devs[0].id)) == 1
    # 과열 / 저장공간 부족 / 연결 끊김 상태 갱신
    s = farm.provider.serials
    farm.provider.faults.update({s[0]: "overheat", s[1]: "low_storage", s[2]: "offline"})
    farm.cycle()
    db.expire_all()
    status = {d.serial: d.status for d in db.scalars(select(Device).where(Device.agent_id == farm.info["id"]))}
    assert status[s[0]] == "overheat" and status[s[1]] == "low_storage" and status[s[2]] == "offline" and status[s[3]] == "idle"
    # 관리자 설정: 유지보수 / 사용 중지 / Google 계정 확인(비밀번호는 저장 항목 자체가 없음)
    did = next(d.id for d in devs if d.serial == s[3])
    r = client.patch(f"/api/admin/devices/{did}", headers=admin, json={"maintenance": True, "google_account_confirmed": True, "name": "S20-04"})
    assert r.json()["status"] == "maintenance" and r.json()["google_account_confirmed"] is True
    assert client.patch(f"/api/admin/devices/{did}", headers=admin, json={"maintenance": False, "enabled": False}).json()["status"] == "disabled"
    assert not any("password" in c.name for c in Device.__table__.columns)
    farm.provider.faults.clear()


def test_disconnect_detection_and_reconnect(client, admin, farm, db):
    from app.models import Agent, Device
    from app.services import scheduler
    from app.db import utcnow
    stats = scheduler.tick_devices(db, utcnow() + timedelta(minutes=5))     # 하트비트 없이 5분 경과
    assert stats["agents_offline"] >= 1 and stats["devices_offline"] >= 6
    db.expire_all()
    assert db.get(Agent, farm.info["id"]).status == "offline"
    assert all(d.status == "offline" for d in db.scalars(select(Device).where(Device.agent_id == farm.info["id"])))
    notes = client.get("/api/notifications", headers=admin).json()["items"]
    assert any(n["event"] == "device_disconnected" for n in notes)          # 관리자 알림
    farm.cycle()                                                            # 재접속
    db.expire_all()
    assert db.get(Agent, farm.info["id"]).status == "online"
    assert all(d.status == "idle" for d in db.scalars(select(Device).where(Device.agent_id == farm.info["id"])))


def test_auto_allocation_wait_then_assign(client, admin, customer, mock_pg, db):
    """가용 기기 부족 → 자동 대기 → 기기 확보 시 자동 배정. 모의 주문에는 모의 기기만 배정된다."""
    from app.models import DeviceAssignment, Order, TestPlan
    from app.services import scheduler
    retire_all(db)
    app, version = customer.make_app()
    order = customer.order(app, version)                    # BASIC: 5대
    res, _ = customer.pay(order)
    assert res.status_code == 200
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))
    assert plan.status == "waiting_devices"
    small = Farm(client, admin, count=3)
    small.cycle()
    assert scheduler.tick_allocate(db) == 0                 # 3대뿐: 계속 대기
    more = Farm(client, admin, count=4)
    more.cycle()
    assert scheduler.tick_allocate(db) == 1
    db.expire_all()
    plan = db.get(TestPlan, plan.id)
    assigned = db.scalars(select(DeviceAssignment).where(DeviceAssignment.plan_id == plan.id)).all()
    assert plan.status == "scheduled" and len(assigned) == 5 and len({a.device_id for a in assigned}) == 5
    assert all(a.device.is_mock for a in assigned)
    assert db.get(Order, order["id"]).status == "scheduled"
    events = [n["event"] for n in client.get("/api/notifications", headers=customer.h).json()["items"]]
    assert "test_delayed" in events and "devices_assigned" in events
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)
    small.retire(db)
    more.retire(db)


def test_real_orders_never_get_mock_devices(client, admin, customer, farm, db):
    """실제 결제 주문(is_mock=False)에는 모의 기기가 배정되지 않는다."""
    from app.models import Order, Payment, TestPlan
    from app.services import orders as order_svc
    app, version = customer.make_app()
    order = customer.order(app, version)
    o = db.get(Order, order["id"])
    pay = Payment(order_id=o.id, provider="toss", mode="test", amount=o.final_amount, status="paid", payment_key="unit-real-key")
    db.add(pay)
    plan = order_svc.on_payment_confirmed(db, o, pay)
    db.commit()
    assert plan.is_mock is False and plan.status == "waiting_devices"       # 모의 기기 6대가 있어도 배정하지 않음
    order_svc.stop_plan(db, plan, "cancelled")
    db.commit()


def test_job_claim_run_and_store_results(client, admin, customer, mock_pg, farm, db):
    from app.models import CrashLog, PerformanceMetric, Screenshot, TestJob, TestPlan, TestResult
    from app.services import scheduler
    app, version = customer.make_app()
    order = customer.order(app, version, "STANDARD") if False else customer.order(app, version)
    customer.pay(order)
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))
    assert plan.status == "scheduled"
    crash_serial = farm.provider.serials[0]
    farm.provider.faults[crash_serial] = "crash"
    assert scheduler.tick_schedules(db) == 5
    assert scheduler.tick_schedules(db) == 0                                # 같은 회차 중복 생성 없음
    farm.cycle()
    db.expire_all()
    jobs = db.scalars(select(TestJob).where(TestJob.plan_id == plan.id)).all()
    assert len(jobs) == 5 and all(j.status == "succeeded" and j.is_mock for j in jobs)
    results = db.scalars(select(TestResult).where(TestResult.plan_id == plan.id)).all()
    assert len(results) == 5 and all(r.is_mock for r in results)
    by_serial = {r.device.serial: r for r in results}
    crashed = [r for r in results if r.device.serial == crash_serial]
    if crashed:                                                             # 크래시 기기가 배정된 경우
        assert crashed[0].status == "failed" and crashed[0].crash_count == 1
        log = db.scalar(select(CrashLog).where(CrashLog.result_id == crashed[0].id, CrashLog.kind == "crash"))
        assert log.category == "널 참조" and log.analysis_source == "rule" and log.is_mock
    ok = [r for r in results if r.device.serial != crash_serial]
    assert all(r.status == "passed" for r in ok) and by_serial
    assert all(s["status"] in ("passed", "failed", "not_run") for r in results for s in r.steps)
    assert db.scalar(select(func.count()).select_from(Screenshot).where(Screenshot.plan_id == plan.id)) >= len(ok) * 2
    assert db.scalar(select(func.count()).select_from(PerformanceMetric).where(PerformanceMetric.plan_id == plan.id)) > 0
    # 고객 화면 API
    detail = client.get(f"/api/plans/{plan.id}", headers=customer.h).json()
    assert detail["total_runs"] == 5 and detail["status"] == "running" and len(detail["devices"]) == 5
    shots = client.get(f"/api/plans/{plan.id}/screenshots", headers=customer.h).json()
    img = client.get(shots[0]["url"])
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    assert client.get(shots[0]["url"].split("sig=")[0] + "sig=tampered").status_code == 403
    dash = client.get("/api/dashboard", headers=customer.h).json()
    assert dash["runs_total"] == 5 and dash["apps"] == 1
    # 앱 상세(현재 상태·리포트·일별 실행 기록)
    ov = client.get(f"/api/apps/{app['id']}/overview", headers=customer.h).json()
    assert ov["plan"]["status"] == "running" and ov["plan"]["day_no"] == 1 and ov["report"] == {"day_no": 1, "devices": 5, "runs": 5}
    day = ov["days"][0]
    assert day["total"] == 5 and len(day["cells"]) == 5 and day["confirmed"] == len(ok)
    cell = next(c for c in day["cells"] if c["serial"] != crash_serial)
    assert cell["launched"] and client.get(cell["screenshot_url"]).content.startswith(b"\x89PNG")
    from conftest import Cust
    assert client.get(f"/api/apps/{app['id']}/overview", headers=Cust(client).h).status_code == 404
    farm.provider.faults.clear()
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_result_cannot_be_recorded_as_pass_without_execution(client, admin, customer, mock_pg, farm, db):
    """수행하지 않은 검사를 성공으로 기록할 수 없다."""
    from app.models import TestPlan
    from app.services import scheduler
    app, version = customer.make_app()
    order = customer.order(app, version)
    customer.pay(order)
    plan = db.scalar(select(TestPlan).where(TestPlan.order_id == order["id"]))
    scheduler.tick_schedules(db)
    farm.agent.heartbeat()
    job = farm.api.claim(1)[0]
    h = {"X-Agent-Token": farm.cfg.token}
    base = {"lease_token": job["lease_token"]}
    bad1 = client.post(f"/api/agent/jobs/{job['id']}/result", headers=h, json={**base, "status": "passed", "steps": []})
    bad2 = client.post(f"/api/agent/jobs/{job['id']}/result", headers=h, json={
        **base, "status": "passed", "steps": [{"key": "launch", "name": "실행", "status": "failed"}]})
    bad3 = client.post(f"/api/agent/jobs/{job['id']}/result", headers=h, json={
        **base, "status": "passed", "steps": [{"key": "launch", "name": "실행", "status": "not_run"}]})
    assert (bad1.status_code, bad2.status_code, bad3.status_code) == (400, 400, 400)
    wrong = client.post(f"/api/agent/jobs/{job['id']}/result", headers=h, json={
        "lease_token": "wrong", "status": "failed", "steps": [{"key": "launch", "name": "실행", "status": "failed"}]})
    assert wrong.status_code == 409
    client.post(f"/api/admin/plans/{plan.id}/cancel", headers=admin)


def test_remote_commands_are_allowlisted(client, admin, customer, farm, db):
    ids = farm.device_ids(db)
    assert client.post("/api/admin/commands", headers=admin, json={"device_ids": ids[:1], "type": "shell", "params": {"cmd": "rm -rf /"}}).status_code == 400
    assert client.post("/api/admin/commands", headers=admin, json={"device_ids": ids[:1], "type": "launch",
                                                                    "params": {"package": "com.not.registered"}}).status_code == 400
    app, version = customer.make_app()
    sent = client.post("/api/admin/commands", headers=admin, json={"device_ids": ids[:3], "type": "screenshot"}).json()
    inst = client.post("/api/admin/commands", headers=admin, json={"device_ids": ids[:1], "type": "install_apk",
                                                                    "params": {"app_version_id": version["id"]}}).json()
    farm.cycle()
    got = client.get("/api/admin/commands?ids=" + ",".join(str(c["id"]) for c in sent + inst), headers=admin).json()
    assert all(c["status"] == "done" for c in got)
    shot = next(c for c in got if c["type"] == "screenshot")
    assert client.get(shot["result"]["screenshot_url"]).content.startswith(b"\x89PNG")
    ver = client.post("/api/admin/commands", headers=admin, json={"device_ids": ids[:1], "type": "app_version",
                                                                   "params": {"package": app["package_name"]}}).json()
    farm.cycle()
    out = client.get(f"/api/admin/commands?ids={ver[0]['id']}", headers=admin).json()[0]
    assert "설치 버전" in out["result"]["message"]


def test_apk_download_restricted_to_assigned_agent(client, admin, customer, mock_pg, farm, db):
    from app.models import AppFile
    app, version = customer.make_app()
    file_id = db.scalar(select(AppFile.id).where(AppFile.app_id == app["id"], AppFile.kind == "apk"))
    assert client.get(f"/api/agent/files/{file_id}", headers={"X-Agent-Token": farm.cfg.token}).status_code == 403
    assert client.get(f"/api/agent/files/{file_id}").status_code == 401
    assert client.get(f"/api/agent/files/{file_id}", headers=customer.h).status_code == 401
