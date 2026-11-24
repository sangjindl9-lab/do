"""데이터베이스 모델. 모든 시각은 UTC(timezone-aware)."""
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
                        JSON, String, Table, Text, UniqueConstraint, text)
from sqlalchemy.orm import relationship

from .db import Base, utcnow


def TS(**kw):
    return Column(DateTime(timezone=True), **kw)


def FK(target, **kw):
    kw.setdefault("index", True)
    return Column(Integer, ForeignKey(target, ondelete=kw.pop("ondelete", "RESTRICT")), **kw)


role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    is_staff = Column(Boolean, default=False, nullable=False)
    permissions = relationship("Permission", secondary=role_permissions, lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True)
    code = Column(String(60), unique=True, nullable=False)
    name = Column(String(120), nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    username = Column(String(60), unique=True)
    password_hash = Column(String(255))
    name = Column(String(120), default="")
    role_id = FK("roles.id", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    failed_logins = Column(Integer, default=0, nullable=False)
    locked_until = TS()
    must_change_password = Column(Boolean, default=False, nullable=False)
    google_sub = Column(String(80), unique=True)
    locale = Column(String(8), default="ko")
    created_at = TS(default=utcnow, nullable=False)
    last_login_at = TS()
    deleted_at = TS()
    role = relationship("Role", lazy="joined")
    customer = relationship("Customer", uselist=False, back_populates="user", lazy="joined")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    kind = Column(String(20), default="individual", nullable=False)
    company = Column(String(160), default="")
    phone = Column(String(40), default="")
    business_no = Column(String(40), default="")
    created_at = TS(default=utcnow, nullable=False)
    user = relationship("User", back_populates="customer")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True)
    user_id = FK("users.id", nullable=False, ondelete="CASCADE")
    refresh_hash = Column(String(64), unique=True, nullable=False)
    user_agent = Column(String(300), default="")
    ip = Column(String(60), default="")
    created_at = TS(default=utcnow, nullable=False)
    expires_at = TS(nullable=False)
    rotated_at = TS()
    revoked_at = TS()


class LoginHistory(Base):
    __tablename__ = "login_history"
    id = Column(Integer, primary_key=True)
    user_id = FK("users.id", ondelete="SET NULL")
    identifier = Column(String(255), default="")
    ip = Column(String(60), default="")
    user_agent = Column(String(300), default="")
    success = Column(Boolean, nullable=False)
    reason = Column(String(60), default="")
    created_at = TS(default=utcnow, nullable=False, index=True)


class UserToken(Base):
    __tablename__ = "user_tokens"
    id = Column(Integer, primary_key=True)
    user_id = FK("users.id", nullable=False, ondelete="CASCADE")
    purpose = Column(String(30), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = TS(nullable=False)
    used_at = TS()


class App(Base):
    __tablename__ = "apps"
    __table_args__ = (UniqueConstraint("customer_id", "package_name", name="uq_app_customer_package"),)
    id = Column(Integer, primary_key=True)
    customer_id = FK("customers.id", nullable=False)
    name = Column(String(160), nullable=False)
    package_name = Column(String(255), nullable=False)
    icon_file_id = Column(Integer)
    play_url = Column(String(500), default="")
    closed_test_url = Column(String(500), default="")
    google_group = Column(String(255), default="")
    description = Column(Text, default="")
    request_notes = Column(Text, default="")
    languages = Column(JSON, default=list)
    test_login_enc = Column(Text, default="")
    ownership_confirmed = Column(Boolean, default=False, nullable=False)
    ownership_confirmed_at = TS()
    closed_test_started_on = Column(String(10), default="")
    improvements = Column(Text, default="")
    created_at = TS(default=utcnow, nullable=False)
    deleted_at = TS()
    versions = relationship("AppVersion", order_by="AppVersion.version_code.desc()", lazy="selectin")


class AppFile(Base):
    __tablename__ = "app_files"
    id = Column(Integer, primary_key=True)
    app_id = FK("apps.id", ondelete="CASCADE")
    customer_id = FK("customers.id", nullable=False)
    kind = Column(String(20), nullable=False)
    filename = Column(String(255), nullable=False)
    path = Column(String(500), nullable=False)
    size = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(20), default="clean", nullable=False)
    quarantine_reason = Column(String(255), default="")
    created_at = TS(default=utcnow, nullable=False)


class AppVersion(Base):
    __tablename__ = "app_versions"
    __table_args__ = (UniqueConstraint("app_id", "version_code", name="uq_app_version_code"),)
    id = Column(Integer, primary_key=True)
    app_id = FK("apps.id", nullable=False, ondelete="CASCADE")
    version_name = Column(String(60), nullable=False)
    version_code = Column(Integer, nullable=False)
    file_id = FK("app_files.id")
    notes = Column(Text, default="")
    created_at = TS(default=utcnow, nullable=False)
    file = relationship("AppFile", lazy="joined")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    description_en = Column(Text, default="")
    list_price = Column(Integer, default=0, nullable=False)
    discount_price = Column(Integer, default=0, nullable=False)
    price = Column(Integer, default=0, nullable=False)
    duration_days = Column(Integer, default=7, nullable=False)
    device_count = Column(Integer, default=5, nullable=False)
    daily_runs = Column(Integer, default=1, nullable=False)
    checks = Column(JSON, default=list)
    ai_analysis = Column(Boolean, default=False, nullable=False)
    pdf_report = Column(Boolean, default=True, nullable=False)
    excel_report = Column(Boolean, default=False, nullable=False)
    priority = Column(Boolean, default=False, nullable=False)
    coupon_allowed = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_quote = Column(Boolean, default=False, nullable=False)
    sort = Column(Integer, default=0, nullable=False)


class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)
    kind = Column(String(10), default="percent", nullable=False)
    value = Column(Integer, nullable=False)
    max_uses = Column(Integer, default=0, nullable=False)
    used_count = Column(Integer, default=0, nullable=False)
    min_amount = Column(Integer, default=0, nullable=False)
    valid_from = TS()
    valid_to = TS()
    is_active = Column(Boolean, default=True, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_no = Column(String(40), unique=True, nullable=False)
    customer_id = FK("customers.id", nullable=False)
    app_id = FK("apps.id", nullable=False)
    app_version_id = FK("app_versions.id", nullable=False)
    product_id = FK("products.id", nullable=False)
    product_snapshot = Column(JSON, nullable=False)
    scenario_id = FK("test_scenarios.id")
    status = Column(String(30), default="pending_payment", nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    discount = Column(Integer, default=0, nullable=False)
    coupon_id = FK("coupons.id")
    final_amount = Column(Integer, nullable=False)
    desired_start = TS()
    desired_android = Column(String(20), default="")
    request_notes = Column(Text, default="")
    is_mock = Column(Boolean, default=False, nullable=False)
    idempotency_key = Column(String(80), unique=True)
    created_at = TS(default=utcnow, nullable=False)
    paid_at = TS()
    completed_at = TS()
    app = relationship("App", lazy="joined")
    product = relationship("Product", lazy="joined")
    app_version = relationship("AppVersion", lazy="joined")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("uq_payment_one_paid_per_order", "order_id", unique=True,
              postgresql_where=text("status in ('paid','partial_refunded','refunded')")),
    )
    id = Column(Integer, primary_key=True)
    order_id = FK("orders.id", nullable=False)
    provider = Column(String(30), nullable=False)
    mode = Column(String(10), nullable=False)
    payment_key = Column(String(200), unique=True)
    method = Column(String(40), default="")
    amount = Column(Integer, nullable=False)
    status = Column(String(30), default="ready", nullable=False, index=True)
    refunded_amount = Column(Integer, default=0, nullable=False)
    receipt_url = Column(String(500), default="")
    raw = Column(JSON)
    failure_code = Column(String(80), default="")
    failure_message = Column(String(500), default="")
    approved_at = TS()
    created_at = TS(default=utcnow, nullable=False)
    order = relationship("Order", lazy="joined")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_payment_event"),)
    id = Column(Integer, primary_key=True)
    provider = Column(String(30), nullable=False)
    event_id = Column(String(200), nullable=False)
    event_type = Column(String(80), default="")
    payment_id = FK("payments.id")
    payload = Column(JSON)
    processed = Column(Boolean, default=False, nullable=False)
    note = Column(String(300), default="")
    created_at = TS(default=utcnow, nullable=False)


class Refund(Base):
    __tablename__ = "refunds"
    id = Column(Integer, primary_key=True)
    payment_id = FK("payments.id", nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(String(300), default="")
    status = Column(String(20), default="done", nullable=False)
    provider_ref = Column(String(200), default="")
    idempotency_key = Column(String(80), unique=True)
    requested_by = FK("users.id")
    created_at = TS(default=utcnow, nullable=False)


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True)
    uid = Column(String(40), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    kind = Column(String(10), default="real", nullable=False)  # real | mock
    hostname = Column(String(160), default="")
    os = Column(String(80), default="")
    version = Column(String(30), default="")
    status = Column(String(20), default="pending", nullable=False)
    enroll_code_hash = Column(String(64), unique=True)
    enroll_expires_at = TS()
    last_seen_at = TS()
    ip = Column(String(60), default="")
    created_at = TS(default=utcnow, nullable=False)


class AgentToken(Base):
    __tablename__ = "agent_tokens"
    id = Column(Integer, primary_key=True)
    agent_id = FK("agents.id", nullable=False, ondelete="CASCADE")
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = TS(nullable=False)
    revoked_at = TS()
    created_at = TS(default=utcnow, nullable=False)


class DeviceGroup(Base):
    __tablename__ = "device_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    description = Column(String(300), default="")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("agent_id", "serial", name="uq_device_agent_serial"),)
    id = Column(Integer, primary_key=True)
    agent_id = FK("agents.id", nullable=False)
    serial = Column(String(120), nullable=False)
    name = Column(String(120), default="")
    group_id = FK("device_groups.id", ondelete="SET NULL")
    manufacturer = Column(String(80), default="")
    model = Column(String(120), default="")
    android_version = Column(String(20), default="")
    sdk = Column(Integer, default=0)
    cpu = Column(String(120), default="")
    ram_mb = Column(Integer, default=0)
    storage_total_mb = Column(Integer, default=0)
    storage_free_mb = Column(Integer, default=0)
    battery = Column(Integer, default=0)
    temperature = Column(Float, default=0)
    resolution = Column(String(30), default="")
    network = Column(String(40), default="")
    conn_state = Column(String(20), default="offline", nullable=False)
    status = Column(String(20), default="offline", nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    maintenance = Column(Boolean, default=False, nullable=False)
    google_account_confirmed = Column(Boolean, default=False, nullable=False)
    is_mock = Column(Boolean, default=False, nullable=False)
    installed_apps = Column(JSON, default=dict)
    last_seen_at = TS()
    last_test_at = TS()
    notes = Column(Text, default="")
    created_at = TS(default=utcnow, nullable=False)
    agent = relationship("Agent", lazy="joined")
    group = relationship("DeviceGroup", lazy="joined")


class DeviceHeartbeat(Base):
    __tablename__ = "device_heartbeats"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    device_id = FK("devices.id", nullable=False, ondelete="CASCADE")
    battery = Column(Integer, default=0)
    temperature = Column(Float, default=0)
    storage_free_mb = Column(Integer, default=0)
    status = Column(String(20), default="")
    created_at = TS(default=utcnow, nullable=False, index=True)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    id = Column(Integer, primary_key=True)
    device_id = FK("devices.id", nullable=False, ondelete="CASCADE")
    agent_id = FK("agents.id", nullable=False)
    type = Column(String(40), nullable=False)
    params = Column(JSON, default=dict)
    status = Column(String(20), default="queued", nullable=False, index=True)
    result = Column(JSON)
    created_by = FK("users.id")
    created_at = TS(default=utcnow, nullable=False)
    finished_at = TS()


class TestScenario(Base):
    __tablename__ = "test_scenarios"
    __test__ = False
    id = Column(Integer, primary_key=True)
    customer_id = FK("customers.id")
    app_id = FK("apps.id", ondelete="SET NULL")
    name = Column(String(160), nullable=False)
    version = Column(Integer, default=1, nullable=False)
    root_id = Column(Integer, index=True)
    steps = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = FK("users.id")
    created_at = TS(default=utcnow, nullable=False)


class TestPlan(Base):
    __tablename__ = "test_plans"
    __test__ = False
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=False)
    customer_id = FK("customers.id", nullable=False)
    app_id = FK("apps.id", nullable=False)
    app_version_id = FK("app_versions.id", nullable=False)
    scenario_id = FK("test_scenarios.id")
    device_count = Column(Integer, nullable=False)
    daily_runs = Column(Integer, default=1, nullable=False)
    checks = Column(JSON, default=list)
    desired_android = Column(String(20), default="")
    start_at = TS(nullable=False)
    end_at = TS(nullable=False)
    status = Column(String(30), default="waiting_devices", nullable=False, index=True)
    priority = Column(Integer, default=0, nullable=False)
    is_mock = Column(Boolean, default=False, nullable=False)
    ending_notified = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False)
    order = relationship("Order", lazy="joined")
    app = relationship("App", lazy="joined")
    app_version = relationship("AppVersion", lazy="joined")


class TestSchedule(Base):
    __tablename__ = "test_schedules"
    __test__ = False
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("test_plans.id", ondelete="CASCADE"), unique=True, nullable=False)
    run_times = Column(JSON, default=list)  # ["09:00","15:00"] (UTC)
    next_run_at = TS(index=True)
    last_run_at = TS()
    status = Column(String(20), default="active", nullable=False)


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"
    __table_args__ = (UniqueConstraint("plan_id", "device_id", name="uq_assignment_plan_device"),)
    id = Column(Integer, primary_key=True)
    plan_id = FK("test_plans.id", nullable=False, ondelete="CASCADE")
    device_id = FK("devices.id", nullable=False)
    status = Column(String(20), default="active", nullable=False)
    assigned_at = TS(default=utcnow, nullable=False)
    released_at = TS()
    device = relationship("Device", lazy="joined")


class TestJob(Base):
    __tablename__ = "test_jobs"
    __test__ = False
    __table_args__ = (
        UniqueConstraint("plan_id", "device_id", "run_key", name="uq_job_plan_device_run"),
        Index("ix_job_claim", "status", "agent_id", "next_attempt_at"),
        Index("uq_job_one_active_per_device", "device_id", unique=True,
              postgresql_where=text("status in ('leased','running')")),
    )
    id = Column(Integer, primary_key=True)
    plan_id = FK("test_plans.id", nullable=False, ondelete="CASCADE")
    device_id = FK("devices.id", nullable=False)
    agent_id = FK("agents.id", nullable=False)
    app_version_id = FK("app_versions.id", nullable=False)
    run_key = Column(String(60), nullable=False)
    kind = Column(String(20), default="scheduled", nullable=False)
    status = Column(String(20), default="queued", nullable=False)
    priority = Column(Integer, default=0, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    next_attempt_at = TS(default=utcnow, nullable=False)
    lease_token = Column(String(64))
    lease_expires_at = TS()
    timeout_sec = Column(Integer, default=1800, nullable=False)
    payload = Column(JSON, nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    started_at = TS()
    finished_at = TS()
    error = Column(Text, default="")
    is_mock = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False)
    device = relationship("Device", lazy="joined")


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("test_jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    plan_id = FK("test_plans.id", nullable=False, ondelete="CASCADE")
    device_id = FK("devices.id", nullable=False)
    app_version_id = FK("app_versions.id", nullable=False)
    customer_id = FK("customers.id", nullable=False)
    status = Column(String(20), nullable=False)  # passed | failed | error
    steps = Column(JSON, default=list)
    summary = Column(JSON, default=dict)
    device_info = Column(JSON, default=dict)
    started_at = TS()
    finished_at = TS()
    duration_ms = Column(Integer, default=0)
    crash_count = Column(Integer, default=0, nullable=False)
    anr_count = Column(Integer, default=0, nullable=False)
    is_mock = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False, index=True)
    device = relationship("Device", lazy="joined")


class Screenshot(Base):
    __tablename__ = "screenshots"
    id = Column(Integer, primary_key=True)
    job_id = FK("test_jobs.id", ondelete="CASCADE")
    command_id = FK("device_commands.id", ondelete="CASCADE")
    device_id = FK("devices.id", nullable=False)
    customer_id = FK("customers.id")
    plan_id = FK("test_plans.id", ondelete="CASCADE")
    label = Column(String(160), default="")
    path = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size = Column(Integer, nullable=False)
    is_mock = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False)


class CrashLog(Base):
    __tablename__ = "crash_logs"
    id = Column(Integer, primary_key=True)
    result_id = FK("test_results.id", nullable=False, ondelete="CASCADE")
    plan_id = FK("test_plans.id", nullable=False, ondelete="CASCADE")
    device_id = FK("devices.id", nullable=False)
    customer_id = FK("customers.id", nullable=False)
    app_version_id = FK("app_versions.id", nullable=False)
    kind = Column(String(20), nullable=False)  # crash | anr | logcat_error
    signature = Column(String(64), nullable=False, index=True)
    title = Column(String(300), default="")
    detail = Column(Text, default="")
    severity = Column(String(20), default="medium")
    category = Column(String(60), default="")
    analysis = Column(JSON)
    analysis_source = Column(String(20), default="rule")  # rule(규칙 기반) | ai(AI 추정)
    is_mock = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False)


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"
    id = Column(Integer, primary_key=True)
    result_id = FK("test_results.id", nullable=False, ondelete="CASCADE")
    plan_id = FK("test_plans.id", nullable=False, ondelete="CASCADE")
    device_id = FK("devices.id", nullable=False)
    metric = Column(String(40), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(20), default="")
    created_at = TS(default=utcnow, nullable=False)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    report_no = Column(String(40), unique=True, nullable=False)
    plan_id = FK("test_plans.id", nullable=False, ondelete="CASCADE")
    customer_id = FK("customers.id", nullable=False)
    kind = Column(String(30), nullable=False)
    fmt = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    size = Column(Integer, default=0)
    is_mock = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False)


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    __table_args__ = (UniqueConstraint("event", "locale", name="uq_template_event_locale"),)
    id = Column(Integer, primary_key=True)
    event = Column(String(40), nullable=False)
    locale = Column(String(8), default="ko", nullable=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = FK("users.id", nullable=False, ondelete="CASCADE")
    event = Column(String(40), nullable=False)
    channel = Column(String(10), nullable=False)  # web | email
    title = Column(String(200), nullable=False)
    body = Column(Text, default="")
    link = Column(String(300), default="")
    status = Column(String(20), nullable=False, index=True)  # web: unread/read, email: queued/sent/failed/not_sent_no_smtp
    attempts = Column(Integer, default=0, nullable=False)
    next_attempt_at = TS()
    last_error = Column(String(300), default="")
    sent_at = TS()
    created_at = TS(default=utcnow, nullable=False)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True)
    customer_id = FK("customers.id", nullable=False)
    subject = Column(String(200), nullable=False)
    category = Column(String(40), default="general")
    status = Column(String(20), default="open", nullable=False)
    created_at = TS(default=utcnow, nullable=False)
    updated_at = TS(default=utcnow, nullable=False)
    messages = relationship("TicketMessage", order_by="TicketMessage.id", lazy="selectin")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id = Column(Integer, primary_key=True)
    ticket_id = FK("support_tickets.id", nullable=False, ondelete="CASCADE")
    author_id = FK("users.id")
    is_staff = Column(Boolean, default=False, nullable=False)
    body = Column(Text, nullable=False)
    created_at = TS(default=utcnow, nullable=False)


class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, default="")
    is_published = Column(Boolean, default=True, nullable=False)
    pinned = Column(Boolean, default=False, nullable=False)
    created_at = TS(default=utcnow, nullable=False)


class Faq(Base):
    __tablename__ = "faqs"
    id = Column(Integer, primary_key=True)
    question = Column(String(300), nullable=False)
    answer = Column(Text, nullable=False)
    locale = Column(String(8), default="ko", nullable=False)
    sort = Column(Integer, default=0, nullable=False)
    is_published = Column(Boolean, default=True, nullable=False)


class LegalDoc(Base):
    __tablename__ = "legal_docs"
    __table_args__ = (UniqueConstraint("key", "locale", name="uq_legal_key_locale"),)
    id = Column(Integer, primary_key=True)
    key = Column(String(30), nullable=False)  # terms | privacy | refund
    locale = Column(String(8), default="ko", nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, default="")
    updated_at = TS(default=utcnow, nullable=False)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key = Column(String(80), primary_key=True)
    value = Column(Text, default="")
    is_secret = Column(Boolean, default=False, nullable=False)
    updated_at = TS(default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    actor_id = FK("users.id", ondelete="SET NULL")
    action = Column(String(80), nullable=False, index=True)
    target_type = Column(String(40), default="")
    target_id = Column(String(60), default="")
    detail = Column(JSON)
    ip = Column(String(60), default="")
    created_at = TS(default=utcnow, nullable=False, index=True)


class BackupHistory(Base):
    __tablename__ = "backup_history"
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), default="manual", nullable=False)
    path = Column(String(500), default="")
    size = Column(BigInteger, default=0)
    status = Column(String(20), default="done", nullable=False)
    note = Column(String(300), default="")
    created_by = FK("users.id", ondelete="SET NULL")
    created_at = TS(default=utcnow, nullable=False)


class TesterInvite(Base):
    """Google Play 비공개 테스트의 '실제 사람' 테스터 관리. 기기 자동 검사 기록과 분리한다."""
    __tablename__ = "tester_invites"
    __table_args__ = (UniqueConstraint("app_id", "email", name="uq_tester_app_email"),)
    id = Column(Integer, primary_key=True)
    app_id = FK("apps.id", nullable=False, ondelete="CASCADE")
    customer_id = FK("customers.id", nullable=False)
    email = Column(String(255), nullable=False)
    status = Column(String(20), default="invited", nullable=False)  # invited | joined | confirmed
    evidence_file_id = Column(Integer)
    feedback = Column(Text, default="")
    invited_at = TS(default=utcnow, nullable=False)
    joined_at = TS()


class SystemLog(Base):
    __tablename__ = "system_logs"
    id = Column(Integer, primary_key=True)
    level = Column(String(10), default="info", nullable=False)
    source = Column(String(40), default="")
    message = Column(Text, nullable=False)
    created_at = TS(default=utcnow, nullable=False, index=True)
