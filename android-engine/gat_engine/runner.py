"""검사 실행기. 각 단계는 실제 수행 결과만 기록하며, 수행하지 못한 단계는 not_run으로 남긴다."""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .provider import DeviceProvider, ProviderError

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
PERMISSION_UI = ("com.android.permissioncontroller", "com.google.android.permissioncontroller", "com.android.packageinstaller")
ALLOW_IDS = ("permission_allow_foreground_only_button", "permission_allow_button", "permission_allow_one_time_button")
NAMES = {
    "install": "APK 설치", "launch": "앱 실행", "cold_start": "초기 로딩 시간", "display": "앱 화면 표시",
    "orientation": "화면 방향 변경", "restart": "앱 종료 및 재실행", "background": "백그라운드 전환·복귀",
    "permissions": "권한 요청 동작", "network": "네트워크 장애 대응", "crash": "크래시 여부", "anr": "ANR 여부",
    "logcat": "Logcat 오류", "scenario": "고객 지정 시나리오",
}


class JobError(Exception):
    """검사를 수행할 수 없는 상황(기기·ADB 문제). retryable이면 서버가 재시도한다."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Steps:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, key, status, expected="", actual="", detail="", started=None, name=None):
        self.items.append({"key": key, "name": name or NAMES.get(key, key), "status": status, "expected": expected,
                           "actual": actual, "detail": detail,
                           "duration_ms": int((time.monotonic() - started) * 1000) if started else 0})
        return status == "passed"


# ---------------- UI 요소(식별자 기반) ----------------
def find_node(xml: str, selector: dict) -> dict | None:
    """UIAutomator 덤프에서 resource_id / text / content_desc / class_name 으로 요소를 찾는다."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for node in root.iter("node"):
        a = node.attrib
        rid = selector.get("resource_id")
        if rid and not (a.get("resource-id") == rid or a.get("resource-id", "").endswith(":id/" + rid)):
            continue
        if selector.get("text") and selector["text"] not in a.get("text", ""):
            continue
        if selector.get("content_desc") and selector["content_desc"] not in a.get("content-desc", ""):
            continue
        if selector.get("class_name") and a.get("class") != selector["class_name"]:
            continue
        m = BOUNDS_RE.match(a.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        return {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "text": a.get("text", ""), "resource_id": a.get("resource-id", "")}
    return None


def wait_node(provider, serial, selector, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while True:
        node = find_node(provider.dump_ui(serial), selector)
        if node or time.monotonic() >= deadline:
            return node
        time.sleep(0.5)


def _sel_text(sel: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in (sel or {}).items()) or "-"


def run_scenario(provider: DeviceProvider, serial: str, package: str, steps: list[dict], variables: dict | None = None,
                 shot=None, sleep=time.sleep) -> list[dict]:
    """시나리오 실행. 단계별 기대 결과와 실제 결과를 비교해 반환한다. 실패 이후 단계는 not_run."""
    out, failed = [], False
    variables = variables or {}
    for i, step in enumerate(steps, 1):
        action, sel = step.get("action"), step.get("selector") or {}
        name = step.get("name") or f"{i}. {action}"
        expected = step.get("expected") or ""
        item = {"key": f"scenario_{i}", "name": f"[시나리오] {name}", "expected": expected, "actual": "", "detail": "", "duration_ms": 0}
        if failed:
            out.append({**item, "status": "not_run", "actual": "이전 단계 실패로 수행하지 않음"})
            continue
        t0, ok, actual = time.monotonic(), True, ""
        timeout = float(step.get("timeout") or 10)
        try:
            if action == "launch":
                res = provider.launch(serial, package)
                ok, actual = res["ok"], res.get("message") or ("실행됨" if res["ok"] else "실행 실패")
            elif action in ("find", "assert_exists"):
                node = wait_node(provider, serial, sel, timeout)
                ok, actual = bool(node), f"요소 {'발견' if node else '없음'}: {_sel_text(sel)}"
            elif action == "tap":
                if sel:
                    node = wait_node(provider, serial, sel, timeout)
                    ok = bool(node)
                    if node:
                        provider.tap(serial, node["x"], node["y"])
                    actual = f"요소 {'선택' if node else '없음'}: {_sel_text(sel)}"
                else:
                    provider.tap(serial, int(step["x"]), int(step["y"]))
                    actual = f"좌표 선택 ({step['x']},{step['y']})"
            elif action == "input":
                node = wait_node(provider, serial, sel, timeout)
                ok = bool(node)
                if node:
                    text = str(step.get("text", ""))
                    for k, v in variables.items():
                        text = text.replace("{{" + k + "}}", str(v))
                    provider.tap(serial, node["x"], node["y"])
                    provider.input_text(serial, text)
                actual = "입력 완료" if ok else f"입력 대상 없음: {_sel_text(sel)}"
            elif action == "scroll":
                provider.swipe(serial, step.get("direction") or "down")
                actual = "스크롤 수행"
            elif action == "back":
                provider.key(serial, "BACK")
                actual = "뒤로 이동"
            elif action == "home":
                provider.key(serial, "HOME")
                actual = "홈 이동"
            elif action == "wait":
                sleep(float(step.get("seconds") or 1))
                actual = f"{step.get('seconds') or 1}초 대기"
            elif action == "screenshot":
                if shot:
                    shot(name)
                actual = "화면 캡처"
            elif action == "assert_text":
                want = str(step.get("text", ""))
                deadline = time.monotonic() + timeout
                while True:
                    found = want in provider.dump_ui(serial)
                    if found or time.monotonic() >= deadline:
                        break
                    sleep(0.5)
                ok, actual = found, f"텍스트 '{want}' {'확인' if found else '없음'}"
            elif action == "assert_no_error":
                fg = provider.foreground_package(serial)
                alive = provider.pid_of(serial, package) is not None
                ok, actual = alive and fg == package, f"전면 앱={fg or '-'}, 프로세스 {'실행 중' if alive else '종료됨'}"
            elif action == "stop":
                provider.stop(serial, package)
                actual = "앱 종료"
            else:
                ok, actual = False, f"지원하지 않는 동작: {action}"
        except ProviderError as exc:
            ok, actual = False, f"기기 제어 오류: {exc}"
        item.update(status="passed" if ok else "failed", actual=actual, duration_ms=int((time.monotonic() - t0) * 1000))
        out.append(item)
        failed = failed or not ok
    return out


# ---------------- 로그 분석 ----------------
def parse_issues(log: str, package: str) -> list[dict]:
    """Logcat에서 대상 앱의 크래시(FATAL EXCEPTION)·ANR·오류 로그를 추출한다."""
    issues, lines = [], log.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "FATAL EXCEPTION" in line or "Fatal signal" in line:
            block = lines[i:i + 40]
            text = "\n".join(block)
            if package in text or "Fatal signal" in line:
                exc = next((re.sub(r"^.*?:\s(?=[\w.$]+(Exception|Error))", "", l).strip() for l in block[1:6]
                            if re.search(r"(Exception|Error)", l) and "Process:" not in l), line.strip())
                issues.append({"kind": "crash", "title": exc[:300], "detail": text[:8000]})
                i += len(block)
                continue
        elif "ANR in " + package in line:
            issues.append({"kind": "anr", "title": line.split("ANR in", 1)[1].strip()[:300] and f"ANR in {package}",
                           "detail": "\n".join(lines[i:i + 25])[:8000]})
            i += 25
            continue
        i += 1
    errors = [l for l in lines if re.search(r"\sE[\s/]", l) and package in l and "FATAL EXCEPTION" not in l]
    if errors:
        issues.append({"kind": "logcat_error", "title": f"오류 수준 로그 {len(errors)}건", "detail": "\n".join(errors[:60])[:8000]})
    return issues


# ---------------- 검사 본체 ----------------
def run_job(provider: DeviceProvider, serial: str, payload: dict, apk_path: str | None = None, on_progress=None,
            on_screenshot=None, sleep=time.sleep, settle: float = 3.0) -> dict:
    package = payload["package"]
    checks = list(payload.get("checks") or [])
    steps, metrics, started_at, t_start = _Steps(), [], _now(), time.monotonic()

    def progress(pct):
        if on_progress:
            on_progress(pct)

    def shot(label):
        if on_screenshot:
            try:
                on_screenshot(label, provider.screenshot(serial))
            except ProviderError:
                pass

    def alive_front():
        return provider.pid_of(serial, package) is not None, provider.foreground_package(serial)

    state = provider.list_serials().get(serial)
    if state != "device":
        raise JobError(f"기기가 연결되어 있지 않습니다. (상태: {state or '미검출'})")
    try:
        info = provider.describe(serial, [package]).to_dict()
        provider.logcat_clear(serial)
        # 1) 설치
        installed_ok = True
        if "install" in checks or payload.get("apk"):
            t0 = time.monotonic()
            if apk_path:
                ok, msg = provider.install(serial, apk_path)
                installed_ok = steps.add("install", "passed" if ok else "failed", "설치 성공", msg, started=t0)
                if ok:
                    metrics.append({"metric": "install_ms", "value": int((time.monotonic() - t0) * 1000), "unit": "ms"})
            else:
                current = provider.installed_version(serial, package)
                steps.add("install", "not_run", "설치 성공", "APK 미제공: 설치 검사를 수행하지 않음" +
                          (f" (기기에 {current} 설치됨)" if current else ""))
                installed_ok = current is not None
        version = provider.installed_version(serial, package)
        if not installed_ok or version is None:
            if version is None and installed_ok:
                steps.add("launch", "failed", "앱 실행", "기기에 앱이 설치되어 있지 않음")
            for key in checks:
                if key not in ("install",) and not any(s["key"] == key for s in steps.items):
                    steps.add(key, "not_run", "", "앱이 설치되지 않아 수행하지 않음")
            return _finish(steps, metrics, [], info, started_at, t_start, {"installed_version": version})
        progress(15)
        expected_version = payload.get("version_name")
        version_note = {"installed_version": version, "expected_version": expected_version,
                        "version_match": (version == expected_version) if apk_path else None}
        # 2) 실행 + 초기 로딩
        provider.stop(serial, package)
        t0 = time.monotonic()
        res = provider.launch(serial, package)
        sleep(settle)
        alive, front = alive_front()
        launched = res["ok"] and alive
        steps.add("launch", "passed" if launched else "failed", "앱이 실행되어 전면에 표시됨",
                  res.get("message") or f"프로세스 {'실행 중' if alive else '없음'}, 전면 앱={front or '-'}", started=t0)
        if "cold_start" in checks:
            if launched and res.get("total_ms") is not None:
                metrics.append({"metric": "cold_start_ms", "value": res["total_ms"], "unit": "ms"})
                steps.add("cold_start", "passed", "초기 로딩 시간 측정", f"{res['total_ms']} ms")
            else:
                steps.add("cold_start", "not_run", "초기 로딩 시간 측정", "앱이 실행되지 않아 측정하지 못함")
        progress(30)
        if launched:
            shot("앱 실행 직후")
            # 3) 권한 요청
            if "permissions" in checks:
                t0 = time.monotonic()
                perms = provider.permissions(serial, package)
                dialogs = 0
                for _ in range(4):
                    if provider.foreground_package(serial) not in PERMISSION_UI:
                        break
                    xml = provider.dump_ui(serial)
                    node = next((n for n in (find_node(xml, {"resource_id": rid}) for rid in ALLOW_IDS) if n), None)
                    if not node:
                        break
                    provider.tap(serial, node["x"], node["y"])
                    dialogs += 1
                    sleep(1)
                alive, front = alive_front()
                steps.add("permissions", "passed" if alive else "failed", "권한 요청 후에도 앱이 정상 동작",
                          f"선언 권한 {len(perms.get('requested', []))}개, 권한 대화상자 {dialogs}회 처리, "
                          f"프로세스 {'실행 중' if alive else '종료됨'}", started=t0)
            # 4) 화면 표시
            if "display" in checks:
                t0 = time.monotonic()
                xml = provider.dump_ui(serial)
                nodes = xml.count("<node")
                front = provider.foreground_package(serial)
                steps.add("display", "passed" if front == package and nodes > 0 else "failed", "앱 화면이 정상 표시됨",
                          f"전면 앱={front or '-'}, UI 요소 {nodes}개, 해상도 {info.get('resolution') or '-'}", started=t0)
            progress(45)
            # 5) 화면 방향
            if "orientation" in checks:
                t0 = time.monotonic()
                provider.set_rotation(serial, True)
                sleep(1.5)
                alive, front = alive_front()
                shot("가로 화면")
                provider.set_rotation(serial, False)
                sleep(1)
                provider.set_rotation(serial, None)
                steps.add("orientation", "passed" if alive and front == package else "failed", "방향 전환 후에도 앱 유지",
                          f"프로세스 {'실행 중' if alive else '종료됨'}, 전면 앱={front or '-'}", started=t0)
            # 6) 백그라운드 전환·복귀
            if "background" in checks:
                t0 = time.monotonic()
                provider.key(serial, "HOME")
                sleep(1.5)
                back = provider.launch(serial, package)
                sleep(1.5)
                alive, front = alive_front()
                steps.add("background", "passed" if back["ok"] and alive and front == package else "failed",
                          "백그라운드에서 복귀 시 앱이 정상 표시됨", f"복귀 후 전면 앱={front or '-'}", started=t0)
            progress(60)
            # 7) 성능 측정
            m = provider.metrics(serial, package)
            for key, unit in (("cpu_percent", "%"), ("memory_mb", "MB"), ("storage_mb", "MB"), ("temperature_c", "℃")):
                wanted = {"cpu_percent": "cpu", "memory_mb": "memory", "storage_mb": "storage", "temperature_c": "temperature"}[key]
                if wanted in checks and m.get(key) is not None:
                    metrics.append({"metric": key, "value": round(float(m[key]), 2), "unit": unit})
            # 8) 시나리오
            if payload.get("scenario") and "scenario" in checks:
                sc = run_scenario(provider, serial, package, payload["scenario"]["steps"], payload.get("vars"), shot, sleep)
                steps.items.extend(sc)
                shot("시나리오 종료 화면")
            progress(75)
            # 9) 네트워크 장애 대응
            if "network" in checks:
                t0 = time.monotonic()
                if provider.set_network(serial, False):
                    try:
                        provider.stop(serial, package)
                        provider.launch(serial, package)
                        sleep(settle)
                        alive, front = alive_front()
                        shot("네트워크 차단 상태")
                    finally:
                        provider.set_network(serial, True)
                    steps.add("network", "passed" if alive else "failed", "네트워크 차단 시에도 비정상 종료 없음",
                              f"프로세스 {'실행 중' if alive else '종료됨'}", started=t0)
                else:
                    steps.add("network", "not_run", "네트워크 차단 시에도 비정상 종료 없음",
                              "네트워크(TCP) ADB 연결 기기는 연결 유지를 위해 네트워크 차단 검사를 수행하지 않음")
            # 10) 종료·재실행
            if "restart" in checks:
                t0 = time.monotonic()
                provider.stop(serial, package)
                sleep(1)
                stopped = provider.pid_of(serial, package) is None
                again = provider.launch(serial, package)
                sleep(settle)
                alive, front = alive_front()
                steps.add("restart", "passed" if stopped and again["ok"] and alive else "failed", "종료 후 재실행 성공",
                          f"종료 {'확인' if stopped else '실패'}, 재실행 후 프로세스 {'실행 중' if alive else '없음'}", started=t0)
        else:
            for key in checks:
                if key in ("permissions", "display", "orientation", "background", "network", "restart", "scenario"):
                    steps.add(key, "not_run", "", "앱이 실행되지 않아 수행하지 않음")
        progress(88)
        # 11) 크래시 / ANR / Logcat
        issues = parse_issues(provider.logcat_dump(serial), package)
        crashes = [i for i in issues if i["kind"] == "crash"]
        anrs = [i for i in issues if i["kind"] == "anr"]
        if "crash" in checks:
            steps.add("crash", "failed" if crashes else "passed", "크래시 없음", f"크래시 {len(crashes)}건")
        if "anr" in checks:
            steps.add("anr", "failed" if anrs else "passed", "ANR 없음", f"ANR {len(anrs)}건")
        if "logcat" in checks:
            errs = [i for i in issues if i["kind"] == "logcat_error"]
            steps.add("logcat", "passed", "오류 로그 수집", errs[0]["title"] if errs else "오류 수준 로그 없음")
        else:
            issues = [i for i in issues if i["kind"] != "logcat_error"]
        provider.stop(serial, package)
        progress(97)
        return _finish(steps, metrics, issues, info, started_at, t_start, version_note)
    except ProviderError as exc:
        raise JobError(f"기기 제어 오류: {exc}") from exc


def _finish(steps: _Steps, metrics, issues, info, started_at, t_start, summary) -> dict:
    counts = {k: sum(1 for s in steps.items if s["status"] == k) for k in ("passed", "failed", "not_run")}
    status = "failed" if counts["failed"] or not counts["passed"] else "passed"
    if not counts["passed"] and not counts["failed"]:
        steps.add("launch", "failed", "검사 수행", "수행된 검사 단계가 없음")
    return {"status": status, "steps": steps.items, "metrics": metrics, "issues": issues,
            "device_info": {k: info.get(k) for k in ("manufacturer", "model", "android_version", "sdk", "resolution")},
            "summary": {**summary, **counts}, "started_at": started_at, "finished_at": _now(),
            "duration_ms": int((time.monotonic() - t_start) * 1000)}
