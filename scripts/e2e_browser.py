"""실행 중인 서버를 대상으로 한 브라우저 E2E 검증(Playwright).
실제 화면으로 회원가입 → 앱 등록 → APK 업로드 → 주문 → 모의 결제까지 진행하고,
실제 에이전트 프로세스(모의 장비)를 띄워 검사가 수행된 뒤 모든 메뉴를 PC·모바일 폭에서 열어 오류를 확인한다.

사용: python scripts/e2e_browser.py --base http://127.0.0.1:8000 --admin-password '...' [--shots DIR]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("TEST_DATABASE_URL", "postgresql://unused")
PUBLIC = ["/", "/service", "/how-it-works", "/pricing", "/devices", "/faq", "/notices", "/legal/terms", "/legal/privacy", "/legal/refund", "/login", "/register", "/forgot", "/admin/login"]
DASH = ["", "/apps", "/new-test", "/orders", "/results", "/reports", "/scenarios", "/payments", "/support", "/notifications", "/account"]
ADMIN = ["", "/customers", "/users", "/apps", "/orders", "/products", "/coupons", "/payments", "/revenue", "/refunds", "/pg", "/devices", "/device-groups", "/agents", "/incidents",
         "/live", "/jobs", "/plans", "/scenarios", "/results", "/crashes", "/screenshots", "/reports", "/tickets", "/announcements", "/faqs", "/legal", "/settings", "/status",
         "/emails", "/templates", "/audit", "/logs", "/backups", "/account"]


def make_apk(package):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gat_conftest_apk", os.path.join(ROOT, "tests", "apkfixture.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.make_apk(package, 1, "1.0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--shots", default="")
    ap.add_argument("--keep-mock", action="store_true", help="종료 후에도 모의 결제 모드를 유지")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    api = httpx.Client(base_url=base + "/api", timeout=60)
    problems, checked = [], 0

    def admin_headers():
        r = api.post("/auth/login", json={"identifier": "admin", "password": args.admin_password})
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    adm = admin_headers()
    prev_mode = api.get("/admin/pg", headers=adm).json()["state"]["mode"]
    assert api.put("/admin/pg", headers=adm, json={"mode": "mock"}).status_code == 200
    agent = api.post("/admin/agents", headers=adm, json={"name": f"e2e-mock-{uuid.uuid4().hex[:4]}", "kind": "mock"}).json()
    home = tempfile.mkdtemp(prefix="gat-e2e-agent-")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([os.path.join(ROOT, "android-engine"), os.path.join(ROOT, "device-agent")])}
    cli = [sys.executable, "-m", "gat_agent", "--home", home]
    out = subprocess.run([*cli, "enroll", "--server", base, "--code", agent["enroll_code"]], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr + out.stdout
    proc = subprocess.Popen([*cli, "run", "--provider", "mock", "--mock-devices", "20"], env=env)
    email, password, package = f"e2e-{uuid.uuid4().hex[:8]}@example.com", "E2e-passw0rd", f"com.e2e.app{uuid.uuid4().hex[:6]}"
    apk_path = os.path.join(home, "app.apk")
    with open(apk_path, "wb") as fh:
        fh.write(make_apk(package))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", args=["--no-sandbox"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 500 else None)

            def shot(name):
                if args.shots:
                    os.makedirs(args.shots, exist_ok=True)
                    page.screenshot(path=os.path.join(args.shots, name + ".png"), full_page=False)

            # 1) 화면으로 회원가입
            page.goto(base + "/register")
            page.fill('input[type="email"]', email)
            page.fill('input[type="password"]', password)
            page.locator("label:has-text('이름') input").fill("E2E 고객")
            page.check('input[type="checkbox"]')
            page.click("button:has-text('가입하기')")
            page.wait_for_url("**/dashboard")
            # 2) 앱 등록
            page.goto(base + "/dashboard/apps")
            page.click("button:has-text('앱 등록')")
            page.locator("label:has-text('Play Store 링크 또는 패키지명') input").fill(f"https://play.google.com/store/apps/details?id={package}")
            page.click("[role=dialog] button:has-text('불러오기')")
            # 스토어에 없는 앱(비공개 단계)은 이름을 직접 입력한다
            page.locator("[role=dialog] label:has-text('앱 이름') input").fill("E2E 테스트앱")
            page.locator("[role=dialog] input[type=checkbox]").last.check()
            page.click("[role=dialog] button:has-text('등록')")
            page.wait_for_url("**/dashboard/apps/*")
            app_url = page.url
            # 3) APK 업로드(진행률 표시 포함)
            page.click("summary:has-text('버전·APK 파일')")
            page.locator("label:has-text('앱 버전') input").fill("1.0")
            page.locator("label:has-text('버전 코드') input").fill("1")
            page.set_input_files('input[type="file"][accept=".apk"]', apk_path)
            page.click("button:has-text('버전 등록')")
            page.wait_for_selector("td:has-text('app.apk')")
            # 4) 테스트 신청 → 모의 결제
            page.goto(base + "/dashboard/new-test")
            page.locator("label:has-text('앱') select").first.select_option(index=1)
            page.wait_for_timeout(500)
            page.locator("label:has-text('검사할 버전') select").select_option(label="1.0 (1)")
            page.locator("label:has-text('PRO')").first.click()
            page.wait_for_selector("text=14,900원")
            shot("new-test")
            page.click("button:has-text('주문하고 결제하기')")
            page.wait_for_url("**/dashboard/pay/*")
            page.click("button:has-text('모의 결제 승인')")
            page.wait_for_url("**/dashboard/orders/*")
            order_url = page.url
            # 5) 스케줄러(서버 20초 주기)와 실제 에이전트 프로세스가 검사를 수행할 때까지 대기
            deadline, runs = time.time() + 150, 0
            sess = api.post("/auth/login", json={"identifier": email, "password": password}).json()
            ch = {"Authorization": "Bearer " + sess["access_token"]}
            while time.time() < deadline:
                orders = api.get("/orders", headers=ch).json()
                runs = (orders[0].get("plan") or {}).get("total_runs", 0)
                if runs >= 20:
                    break
                time.sleep(5)
            if runs < 20:
                problems.append(f"검사 결과 {runs}/20건만 수신됨")
            plan_id = orders[0]["plan"]["id"]
            api.post(f"/plans/{plan_id}/reports", headers=ch, json={"kind": "comprehensive", "fmt": "pdf"}).raise_for_status()
            ws = [a for a in api.get("/admin/agents", headers=admin_headers()).json() if a["id"] == agent["id"]][0]
            if not ws["ws_connected"]:
                problems.append("에이전트 WebSocket 미연결")
            page.goto(app_url)
            page.wait_for_selector("text=일별 실행 기록")
            page.wait_for_selector("section img")
            if page.locator("section img").count() < 20:
                problems.append("앱 상세의 일별 실행 화면이 20칸 미만")
            page.wait_for_load_state("networkidle")
            if args.shots:
                page.screenshot(path=os.path.join(args.shots, "app-detail.png"), full_page=True)
            for tab in ("status", "devices", "results", "crashes", "screenshots", "reports"):
                page.goto(f"{order_url}?tab={tab}")
                page.wait_for_load_state("networkidle")
                shot(f"order-{tab}")
            # 6) 고객 메뉴 전체
            for path in DASH:
                page.goto(base + "/dashboard" + path)
                page.wait_for_load_state("networkidle")
                checked += 1
                if path in ("", "/reports"):
                    shot("dash" + path.replace("/", "-"))
            # 7) 모바일 폭: 공개 페이지 + 고객 화면 가로 넘침 검사
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, locale="ko-KR", is_mobile=True, storage_state=ctx.storage_state())
            mp = mobile.new_page()
            mp.on("console", lambda m: errors.append("[mobile] " + m.text) if m.type == "error" else None)
            mp.on("pageerror", lambda e: errors.append("[mobile] " + str(e)))
            for path in PUBLIC + ["/dashboard" + p for p in DASH] + [order_url.replace(base, "")]:
                mp.goto(base + path)
                mp.wait_for_load_state("networkidle")
                checked += 1
                over = mp.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 1:
                    problems.append(f"모바일 가로 넘침 {over}px: {path}")
                if args.shots and path in ("/", "/pricing", "/dashboard", "/dashboard/orders"):
                    mp.screenshot(path=os.path.join(args.shots, "m" + (path.replace("/", "-") or "-home") + ".png"))
            mobile.close()
            # 8) 공개 페이지(PC) + 영어 전환
            pub = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")
            pp = pub.new_page()
            pp.on("console", lambda m: errors.append("[public] " + m.text) if m.type == "error" else None)
            for path in PUBLIC:
                pp.goto(base + path)
                pp.wait_for_load_state("networkidle")
                checked += 1
            pp.goto(base + "/")
            if args.shots:
                pp.screenshot(path=os.path.join(args.shots, "home.png"))
            pp.select_option('select[aria-label="Language"]', "en")
            if "Test your app on real phones" not in pp.inner_text("h1"):
                problems.append("영어 전환 실패")
            if args.shots:
                pp.screenshot(path=os.path.join(args.shots, "home-en.png"))
            # 9) 관리자: 화면 로그인 후 전체 메뉴
            pp.select_option('select[aria-label="Language"]', "ko")
            pp.goto(base + "/admin/login")
            pp.locator("label:has-text('관리자 아이디') input").fill("admin")
            pp.fill('input[type="password"]', args.admin_password)
            pp.click("button:has-text('로그인')")
            pp.wait_for_url("**/admin")
            for path in ADMIN:
                pp.goto(base + "/admin" + path)
                pp.wait_for_load_state("networkidle")
                checked += 1
                if pp.locator("text=불러오는 중").count() > 0:
                    pp.wait_for_timeout(1500)
                if "/admin/login" in pp.url:
                    problems.append(f"관리자 화면 접근 실패: {path}")
                if args.shots and path in ("", "/devices", "/payments", "/live", "/settings", "/agents", "/plans"):
                    pp.screenshot(path=os.path.join(args.shots, "admin" + (path.replace("/", "-") or "-home") + ".png"))
            # 관리자 원격 제어: 스크린샷 명령 실제 왕복
            pp.goto(base + "/admin/devices")
            pp.wait_for_selector("text=MOCK")
            pp.click("button:has-text('전체 선택')")
            pp.click("button:has-text('명령 보내기')")
            pp.wait_for_selector("td img", timeout=30000)
            if args.shots:
                pp.screenshot(path=os.path.join(args.shots, "admin-devices-command.png"), full_page=True)
            # 고객은 관리자 화면에 들어갈 수 없다
            page.goto(base + "/admin/devices")
            page.wait_for_load_state("networkidle")
            if "/admin/devices" in page.url:
                problems.append("고객이 관리자 화면에 접근함")
            browser.close()
            problems += [f"브라우저 오류: {e[:300]}" for e in list(dict.fromkeys(errors))[:20]]
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        adm = admin_headers()
        api.post(f"/admin/agents/{agent['id']}/revoke", headers=adm)
        if not args.keep_mock:
            api.put("/admin/pg", headers=adm, json={"mode": prev_mode})
    print(json.dumps({"pages_checked": checked, "test_runs": runs, "customer": email, "problems": problems}, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
