"""선택 사항: Appium(UiAutomator2) 기반 시나리오 드라이버.
Appium 서버와 Appium-Python-Client가 준비된 경우에만 사용하며, 없으면 UIAutomator 덤프 기반 드라이버(runner.run_scenario)가 동작한다.
※ 실기기 + Appium 서버가 있어야 검증할 수 있으므로 '실제 장비 검증 대기' 항목이다."""
import time


def available() -> bool:
    try:
        import appium  # noqa: F401
        return True
    except ImportError:
        return False


def run_scenario_appium(server_url: str, serial: str, package: str, steps: list[dict], variables: dict | None = None) -> list[dict]:
    from appium import webdriver
    from appium.options.android import UiAutomator2Options
    from appium.webdriver.common.appiumby import AppiumBy
    from selenium.common.exceptions import WebDriverException

    opts = UiAutomator2Options()
    opts.udid, opts.no_reset, opts.auto_grant_permissions = serial, True, True
    driver = webdriver.Remote(server_url, options=opts)
    out, failed, variables = [], False, variables or {}

    def locate(sel, timeout):
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sel.get("resource_id"):
                    rid = sel["resource_id"] if ":id/" in sel["resource_id"] else f"{package}:id/{sel['resource_id']}"
                    return driver.find_element(AppiumBy.ID, rid)
                if sel.get("content_desc"):
                    return driver.find_element(AppiumBy.ACCESSIBILITY_ID, sel["content_desc"])
                if sel.get("text"):
                    return driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{sel["text"]}")')
                return driver.find_element(AppiumBy.CLASS_NAME, sel["class_name"])
            except WebDriverException:
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.5)

    try:
        for i, step in enumerate(steps, 1):
            action, sel = step.get("action"), step.get("selector") or {}
            item = {"key": f"scenario_{i}", "name": f"[시나리오] {step.get('name') or action}", "expected": step.get("expected", ""),
                    "actual": "", "detail": "appium", "duration_ms": 0}
            if failed:
                out.append({**item, "status": "not_run", "actual": "이전 단계 실패로 수행하지 않음"})
                continue
            t0, ok, actual = time.monotonic(), True, ""
            try:
                timeout = float(step.get("timeout") or 10)
                if action == "launch":
                    driver.activate_app(package)
                elif action in ("find", "assert_exists"):
                    ok = locate(sel, timeout) is not None
                elif action == "tap":
                    el = locate(sel, timeout)
                    ok = el is not None
                    if el:
                        el.click()
                elif action == "input":
                    el = locate(sel, timeout)
                    ok = el is not None
                    if el:
                        text = str(step.get("text", ""))
                        for k, v in variables.items():
                            text = text.replace("{{" + k + "}}", str(v))
                        el.send_keys(text)
                elif action == "back":
                    driver.back()
                elif action == "wait":
                    time.sleep(float(step.get("seconds") or 1))
                elif action == "assert_text":
                    ok = str(step.get("text", "")) in driver.page_source
                elif action == "assert_no_error":
                    ok = driver.current_package == package
                elif action == "stop":
                    driver.terminate_app(package)
                actual = "성공" if ok else "실패"
            except WebDriverException as exc:
                ok, actual = False, str(exc)[:300]
            out.append({**item, "status": "passed" if ok else "failed", "actual": actual,
                        "duration_ms": int((time.monotonic() - t0) * 1000)})
            failed = failed or not ok
    finally:
        driver.quit()
    return out
