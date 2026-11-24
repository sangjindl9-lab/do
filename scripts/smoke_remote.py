"""배포된 공개 주소에 대한 접속 검증(표준 라이브러리만 사용).
사용: python scripts/smoke_remote.py https://주소
로그인 없이 확인할 수 있는 항목만 검사하며 데이터를 만들지 않는다."""
import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/")
results, failed = [], False


def call(path, method="GET", body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "gat-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read(), dict(res.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def check(name, ok, detail=""):
    global failed
    failed = failed or not ok
    results.append(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


assert base.startswith("https://"), "HTTPS 주소가 필요합니다"
status, body, headers = call("/api/health")
headers = {k.lower(): v for k, v in headers.items()}
health = json.loads(body) if status == 200 else {}
check("서버 헬스체크 /api/health", status == 200 and health.get("status") == "ok", body.decode()[:120])
check("영구 저장소 쓰기 가능", health.get("storage_writable") is True)
check("보안 헤더(HSTS·nosniff)", "max-age" in headers.get("strict-transport-security", "") and headers.get("x-content-type-options") == "nosniff")
for path, name in (("/", "고객 웹사이트 메인"), ("/pricing", "요금제 페이지"), ("/login", "로그인 페이지"), ("/admin", "관리자 페이지"), ("/admin/login", "관리자 로그인 페이지")):
    status, body, _ = call(path)
    check(f"{name} {path}", status == 200 and b'<div id="root">' in body and b"/assets/index-" in body, f"HTTP {status}, {len(body)} bytes")
status, body, _ = call("/api/public/products")
products = json.loads(body) if status == 200 else []
check("상품 API(DB 연동·마이그레이션·초기 데이터)", [p["code"] for p in products][:4] == ["BASIC", "STANDARD", "PRO", "PREMIUM"], str([(p["code"], p["price"]) for p in products]))
status, body, _ = call("/api/public/site")
site = json.loads(body) if status == 200 else {}
check("제3자 서비스 고지 문구", "Google의 공식 서비스가 아닌" in site.get("notice", ""))
check("결제 상태 조회", "payment" in site, str(site.get("payment")))
for path in ("/api/admin/dashboard", "/api/admin/devices", "/api/apps", "/api/orders"):
    status, _, _ = call(path)
    check(f"비로그인 접근 차단 {path}", status == 401, f"HTTP {status}")
status, _, _ = call("/api/agent/heartbeat", "POST", {"devices": []})
check("에이전트 API 인증 요구", status == 401, f"HTTP {status}")
status, _, _ = call("/api/auth/login", "POST", {"identifier": "admin", "password": "wrong-password-0"})
check("잘못된 관리자 비밀번호 거부", status == 401, f"HTTP {status}")
print("\n".join(results))
sys.exit(1 if failed else 0)
