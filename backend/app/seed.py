"""초기 데이터(역할·권한·상품·템플릿·약관·최고관리자). 멱등 실행."""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Faq, LegalDoc, Permission, Product, Role, User
from .security import hash_password
from .services import notifications
from .services.audit import syslog

PERMISSIONS = {
    "dashboard": "통합 대시보드", "customers": "고객·회원 관리", "users": "권한 관리", "orders": "앱·주문 관리",
    "products": "상품·가격·쿠폰 관리", "payments": "결제·환불·PG 설정", "devices": "장비 관리",
    "tests": "검사 관리", "support": "고객지원", "system": "시스템 설정",
}
ROLES = {
    "customer": ("일반 고객", False, []),
    "business": ("기업 고객", False, []),
    "operator": ("기술 운영자", True, ["dashboard", "devices", "tests", "orders"]),
    "support": ("고객지원 담당자", True, ["dashboard", "customers", "support", "orders"]),
    "billing": ("결제 관리자", True, ["dashboard", "payments", "orders", "products"]),
    "superadmin": ("최고관리자", True, list(PERMISSIONS)),
}
BASE_CHECKS = ["install", "launch", "cold_start", "display", "orientation", "restart", "background", "permissions"]
PERF_CHECKS = ["cpu", "memory", "storage", "temperature", "crash", "anr", "logcat"]
PRODUCTS = [
    ("BASIC", "BASIC", 4900, 7, 5, 1, BASE_CHECKS + ["crash", "anr"], False, True, False, False, False),
    ("STANDARD", "STANDARD", 9900, 14, 10, 1, BASE_CHECKS + PERF_CHECKS, False, True, True, False, False),
    ("PRO", "PRO", 14900, 18, 20, 2, BASE_CHECKS + PERF_CHECKS + ["scenario"], True, True, True, False, False),
    ("PREMIUM", "PREMIUM", 29900, 30, 20, 3, BASE_CHECKS + PERF_CHECKS + ["scenario", "network"], True, True, True, True, False),
    ("ENTERPRISE", "ENTERPRISE", 0, 30, 20, 3, BASE_CHECKS + PERF_CHECKS + ["scenario", "network"], True, True, True, True, True),
]
NOTICE = ("본 서비스는 Google의 공식 서비스가 아닌 독립적인 제3자 앱 품질검사 서비스입니다. "
          "검사 기기 수는 실제 검사에 사용되는 기기 수량이며 Google Play 비공개 테스트의 독립적인 참여자 수를 의미하지 않습니다. "
          "프로덕션 승인을 보장하지 않습니다.")
LEGAL = {
    "terms": ("이용약관", "제1조(목적) 본 약관은 구글자동테스터(이하 '서비스')가 제공하는 Android 앱 실기기 자동화 품질검사 서비스의 이용 조건을 정합니다.\n\n"
              "제2조(서비스의 성격) " + NOTICE + "\n\n"
              "제3조(검사 권한) 회원은 본인이 검사 권한을 보유한 앱만 등록·검사할 수 있으며, 권한 없는 앱 등록으로 발생하는 책임은 회원에게 있습니다.\n\n"
              "제4조(금지행위) 허위 참여 기록 생성, Google Play 테스트 요건 우회 목적의 이용, 악성 파일 업로드를 금지합니다.\n\n"
              "※ 운영 개시 전 사업자 정보와 세부 조항을 관리자 페이지에서 확정해 주세요."),
    "privacy": ("개인정보처리방침", "1. 수집 항목: 이메일, 이름, (기업 고객) 회사명·연락처, 결제 식별정보, 서비스 이용기록.\n"
                "2. 이용 목적: 회원 관리, 검사 서비스 제공, 결제 및 환불 처리, 고객 문의 응대.\n"
                "3. 보관 기간: 회원 탈퇴 시 지체 없이 파기하며, 관계 법령상 보관 의무가 있는 정보는 해당 기간 동안 보관합니다.\n"
                "4. 고객이 등록한 테스트용 로그인 정보는 암호화하여 저장하며 검사 목적 외에 사용하지 않습니다.\n"
                "5. 서비스는 검사 기기의 Google 계정 비밀번호를 수집하거나 저장하지 않습니다.\n\n"
                "※ 운영 개시 전 개인정보 보호책임자 정보를 관리자 페이지에서 확정해 주세요."),
    "refund": ("환불 정책", "1. 검사 시작 전: 전액 환불.\n2. 검사 시작 후: 남은 검사 기간에 비례하여 부분 환불.\n"
               "3. 서비스 측 장애로 검사를 수행하지 못한 기간은 연장 또는 환불합니다.\n4. 환불은 결제 수단으로 취소 처리됩니다.\n\n"
               "※ 세부 기준은 운영 정책에 맞게 관리자 페이지에서 수정해 주세요."),
}
FAQS = [
    ("Google 공식 서비스인가요?", "아닙니다. " + NOTICE),
    ("검사 기기 수는 테스터 수와 같은가요?", "아닙니다. 검사 기기 수는 자동화 품질검사를 수행하는 실기기 수량입니다. Google Play 비공개 테스트의 실제 테스터 참여는 별도로 관리됩니다."),
    ("어떤 검사를 수행하나요?", "설치·실행·초기 로딩 시간·화면 표시·화면 회전·백그라운드 전환·권한 요청·크래시·ANR·Logcat 오류·CPU/메모리 사용량 등을 실기기에서 측정합니다."),
    ("검사 결과는 어디서 보나요?", "대시보드의 검사 결과 메뉴에서 기기별·일별 결과, 스크린샷, 오류 로그를 확인하고 PDF/Excel 보고서를 내려받을 수 있습니다."),
]


def run(db: Session) -> None:
    perms = {p.code: p for p in db.scalars(select(Permission))}
    for code, name in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, name=name)
            db.add(perms[code])
    db.flush()
    roles = {r.code: r for r in db.scalars(select(Role))}
    for code, (name, staff, plist) in ROLES.items():
        if code not in roles:
            roles[code] = Role(code=code, name=name, is_staff=staff, permissions=[perms[p] for p in plist])
            db.add(roles[code])
    db.flush()
    if not db.scalar(select(Product.id).limit(1)):
        for i, (code, name, price, days, devs, runs, checks, ai, pdf, xlsx, prio, quote) in enumerate(PRODUCTS):
            db.add(Product(code=code, name=name, list_price=price, discount_price=0, price=price, duration_days=days,
                           device_count=devs, daily_runs=runs, checks=checks, ai_analysis=ai, pdf_report=pdf,
                           excel_report=xlsx, priority=prio, is_quote=quote, sort=i,
                           description=f"실기기 {devs}대 · {days}일 · 하루 {runs}회 자동 검사" if not quote else "기기 수·기간 별도 협의",
                           description_en=f"{devs} real devices · {days} days · {runs} run(s)/day" if not quote else "Custom devices and period"))
    notifications.seed_templates(db)
    if not db.scalar(select(LegalDoc.id).limit(1)):
        for key, (title, body) in LEGAL.items():
            db.add(LegalDoc(key=key, locale="ko", title=title, body=body))
    if not db.scalar(select(Faq.id).limit(1)):
        for i, (q, a) in enumerate(FAQS):
            db.add(Faq(question=q, answer=a, sort=i))
    admin = db.scalar(select(User).where(User.username == settings.ADMIN_USERNAME))
    if admin is None:
        password, generated = settings.ADMIN_PASSWORD, False
        if not password:
            password, generated = secrets.token_urlsafe(12) + "a1", True
        db.add(User(email=settings.ADMIN_EMAIL, username=settings.ADMIN_USERNAME, name="최고관리자",
                    password_hash=hash_password(password), role_id=roles["superadmin"].id, email_verified=True,
                    must_change_password=generated))
        if generated:
            # 환경변수 ADMIN_PASSWORD 미설정 시에만 임시 비밀번호를 서버 로그에 1회 출력한다.
            print(f"[seed] 임시 관리자 비밀번호 발급: {password} (최초 로그인 후 변경 필요)", flush=True)
            syslog(db, "warn", "seed", "ADMIN_PASSWORD 미설정: 임시 관리자 비밀번호가 서버 로그에 출력되었습니다.")
    db.commit()
