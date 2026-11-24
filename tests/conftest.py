"""통합 테스트 공통 설정. 실제 PostgreSQL + Alembic 마이그레이션 + 실제 에이전트 코드(모의 장비)를 사용한다."""
import io
import os
import struct
import sys
import tempfile
import uuid
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "android-engine", "device-agent"):
    sys.path.insert(0, os.path.join(ROOT, sub))

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/gat_test")
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="gat-storage-")
os.environ["SECRET_KEY"] = "test-secret-key-for-automated-tests-only"
os.environ["ADMIN_PASSWORD"] = "Admin-test-pw-1"
os.environ["RUN_SCHEDULER"] = "0"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

ADMIN_PW = os.environ["ADMIN_PASSWORD"]


def make_apk(package: str, version_code: int = 1, version_name: str = "1.0", dex: bool = True, extra: dict | None = None) -> bytes:
    """검증용 최소 APK(바이너리 AndroidManifest 포함)."""
    strings = ["manifest", "package", "versionCode", "versionName", package, version_name]
    blob, offsets = b"", []
    for s in strings:
        offsets.append(len(blob))
        enc = s.encode("utf-16-le")
        blob += struct.pack("<H", len(s)) + enc + b"\x00\x00"
    blob += b"\x00" * (-len(blob) % 4)
    header = 28
    pool = struct.pack("<HHIIIIII", 0x0001, header, header + 4 * len(strings) + len(blob), len(strings), 0, 0,
                       header + 4 * len(strings), 0) + struct.pack(f"<{len(strings)}I", *offsets) + blob
    attrs = (struct.pack("<IIIHBBI", 0xFFFFFFFF, 1, 4, 8, 0, 0x03, 4) +
             struct.pack("<IIIHBBI", 0xFFFFFFFF, 2, 0xFFFFFFFF, 8, 0, 0x10, version_code) +
             struct.pack("<IIIHBBI", 0xFFFFFFFF, 3, 5, 8, 0, 0x03, 5))
    elem = struct.pack("<HHIIIIIHHHHHH", 0x0102, 16, 16 + 20 + len(attrs), 1, 0xFFFFFFFF, 0xFFFFFFFF, 0, 20, 20, 3, 0, 0, 0) + attrs
    manifest = struct.pack("<HHI", 0x0003, 8, 8 + len(pool) + len(elem)) + pool + elem
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AndroidManifest.xml", manifest)
        if dex:
            zf.writestr("classes.dex", b"dex\n035\x00" + uuid.uuid4().bytes)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture(scope="session")
def app():
    from app.db import engine
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = AlembicConfig(os.path.join(ROOT, "backend", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "backend", "alembic"))
    command.upgrade(cfg, "head")  # 실제 마이그레이션으로 스키마 생성
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db(app):
    from app.db import SessionLocal
    with SessionLocal() as session:
        yield session


def login(client, identifier, password):
    res = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture(scope="session")
def admin(client):
    return {"Authorization": "Bearer " + login(client, "admin", ADMIN_PW)["access_token"]}


class Cust:
    def __init__(self, client, email=None, password="Passw0rd-123"):
        self.client, self.password = client, password
        self.email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
        res = client.post("/api/auth/register", json={"email": self.email, "password": password, "name": "테스트 고객",
                                                       "agree_terms": True})
        assert res.status_code == 200, res.text
        self.session = res.json()
        self.h = {"Authorization": "Bearer " + self.session["access_token"]}

    def make_app(self, package=None, version_code=1, apk=True):
        package = package or f"com.test.a{uuid.uuid4().hex[:10]}"
        res = self.client.post("/api/apps", headers=self.h, json={"name": "테스트앱", "package_name": package,
                                                                   "ownership_confirmed": True})
        assert res.status_code == 200, res.text
        app = res.json()
        files = {"file": ("app.apk", make_apk(package, version_code), "application/vnd.android.package-archive")} if apk else None
        res = self.client.post(f"/api/apps/{app['id']}/versions", headers=self.h,
                               data={"version_name": "1.0", "version_code": str(version_code)}, files=files)
        assert res.status_code == 200, res.text
        return app, res.json()

    def order(self, app, version, product_code="BASIC", **extra):
        products = {p["code"]: p for p in self.client.get("/api/public/products").json()}
        res = self.client.post("/api/orders", headers=self.h, json={"app_id": app["id"], "app_version_id": version["id"],
                                                                     "product_id": products[product_code]["id"], **extra})
        assert res.status_code == 200, res.text
        return res.json()

    def pay(self, order, outcome="success"):
        issued = self.client.post("/api/payments/mock/issue", headers=self.h, json={"order_id": order["id"], "outcome": outcome}).json()
        return self.client.post("/api/payments/confirm", headers=self.h, json=issued), issued


@pytest.fixture()
def customer(client):
    return Cust(client)


@pytest.fixture()
def mock_pg(client, admin):
    res = client.put("/api/admin/pg", headers=admin, json={"mode": "mock"})
    assert res.status_code == 200, res.text
    yield
    client.put("/api/admin/pg", headers=admin, json={"mode": "disabled"})


class Farm:
    """실제 에이전트 코드(gat_agent) + 모의 장비(MockProvider)를 테스트 서버에 연결한다."""

    def __init__(self, client, admin, count=6, faults=None, kind="mock"):
        from gat_agent.api import ServerClient
        from gat_agent.config import load
        from gat_agent.core import Agent, enroll
        from gat_engine.providers import MockProvider
        self.client, self.admin = client, admin
        res = client.post("/api/admin/agents", headers=admin, json={"name": f"farm-{uuid.uuid4().hex[:6]}", "kind": kind})
        assert res.status_code == 200, res.text
        self.info = res.json()
        self.cfg = load(tempfile.mkdtemp(prefix="gat-agent-"))
        self.cfg.max_parallel = 50
        enroll(self.cfg, "http://testserver", self.info["enroll_code"], ServerClient("http://testserver", client=client))
        self.provider = MockProvider(count, prefix=f"M{uuid.uuid4().hex[:5].upper()}", faults=faults)
        self.api = ServerClient("http://testserver", self.cfg.token, client=client)
        self.agent = Agent(self.cfg, self.api, self.provider, sleep=lambda s: None, settle=0)

    def cycle(self, n=1):
        for _ in range(n):
            self.agent.tick()
            assert self.agent.wait_idle(60)
        self.agent.flush_spool()

    def device_ids(self, db):
        from app.models import Device
        from sqlalchemy import select
        return list(db.scalars(select(Device.id).where(Device.agent_id == self.info["id"])))

    def retire(self, db):
        """다른 테스트의 기기 배정에 영향을 주지 않도록 사용 중지 처리."""
        from app.models import Device
        db.execute(Device.__table__.update().where(Device.agent_id == self.info["id"]).values(enabled=False, status="disabled"))
        db.commit()


@pytest.fixture()
def farm(client, admin, db):
    f = Farm(client, admin)
    f.cycle()
    yield f
    f.retire(db)
