"""표준 ADB 기반 기기 제어. 제조사 전용 소프트웨어에 의존하지 않는다.
허용된 동작만 메서드로 제공하며 임의 셸 명령을 외부 입력으로 실행하지 않는다."""
import json
import os
import re
import shutil
import subprocess

from ..provider import DeviceInfo, DeviceProvider, ProviderError

PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


class AdbProvider(DeviceProvider):
    name = "adb"

    def __init__(self, adb_path: str = "", timeout: int = 60):
        self.adb = adb_path or shutil.which("adb") or "adb"
        self.timeout = timeout
        self._static: dict[str, dict] = {}

    # ----- 저수준 -----
    def _run(self, args: list[str], timeout: int | None = None, binary: bool = False):
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run([self.adb, *args], capture_output=True, timeout=timeout or self.timeout, creationflags=flags)
        except FileNotFoundError as exc:
            raise ProviderError("adb 실행 파일을 찾을 수 없습니다. platform-tools 경로를 설정해 주세요.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"adb 시간 초과: {' '.join(args[:4])}") from exc
        if binary:
            if proc.returncode != 0:
                raise ProviderError(proc.stderr.decode("utf-8", "replace").strip()[:300])
            return proc.stdout
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        if proc.returncode != 0 and ("device offline" in err or "not found" in err or "unauthorized" in err or "no devices" in err):
            raise ProviderError(err.strip()[:300])
        return out + (("\n" + err) if err and proc.returncode != 0 else "")

    def _sh(self, serial: str, *cmd: str, timeout: int | None = None) -> str:
        return self._run(["-s", serial, "shell", *cmd], timeout)

    @staticmethod
    def _pkg(package: str) -> str:
        if not PKG_RE.match(package):
            raise ProviderError("잘못된 패키지명")
        return package

    # ----- 검색 / 정보 -----
    def list_serials(self) -> dict[str, str]:
        out = self._run(["devices"], 20)
        result = {}
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                result[parts[0]] = parts[1] if parts[1] in ("device", "unauthorized", "offline") else "offline"
        return result

    def _prop(self, serial: str, name: str) -> str:
        return self._sh(serial, "getprop", name).strip()

    def describe(self, serial: str, packages: list[str]) -> DeviceInfo:
        state = self.list_serials().get(serial, "offline")
        info = DeviceInfo(serial=serial, state=state)
        if state != "device":
            return info
        static = self._static.get(serial)
        if static is None:
            mem = re.search(r"MemTotal:\s+(\d+)", self._sh(serial, "cat", "/proc/meminfo"))
            size = re.search(r"(\d+x\d+)", self._sh(serial, "wm", "size"))
            static = {"manufacturer": self._prop(serial, "ro.product.manufacturer"), "model": self._prop(serial, "ro.product.model"),
                      "android_version": self._prop(serial, "ro.build.version.release"),
                      "sdk": int(self._prop(serial, "ro.build.version.sdk") or 0),
                      "cpu": self._prop(serial, "ro.soc.model") or self._prop(serial, "ro.board.platform") or self._prop(serial, "ro.product.cpu.abi"),
                      "ram_mb": int(mem.group(1)) // 1024 if mem else 0, "resolution": size.group(1) if size else ""}
            self._static[serial] = static
        for k, v in static.items():
            setattr(info, k, v)
        df = self._sh(serial, "df", "-k", "/data").splitlines()
        if len(df) >= 2:
            cols = df[-1].split()
            try:
                info.storage_total_mb, info.storage_free_mb = int(cols[1]) // 1024, int(cols[3]) // 1024
            except (IndexError, ValueError):
                pass
        battery = self._sh(serial, "dumpsys", "battery")
        level, temp = re.search(r"level:\s*(\d+)", battery), re.search(r"temperature:\s*(\d+)", battery)
        info.battery = int(level.group(1)) if level else 0
        info.temperature = int(temp.group(1)) / 10 if temp else 0.0
        conn = self._sh(serial, "dumpsys", "connectivity")
        info.network = "wifi" if re.search(r"NetworkAgentInfo.*WIFI.*CONNECTED|type: WIFI.*state: CONNECTED", conn) else \
            ("ethernet" if "ETHERNET" in conn and "CONNECTED" in conn else ("mobile" if "MOBILE" in conn and "CONNECTED" in conn else "none"))
        for pkg in packages[:30]:
            ver = self.installed_version(serial, pkg)
            if ver:
                info.installed[pkg] = ver
        return info

    # ----- 앱 -----
    def install(self, serial, apk_path):
        out = self._run(["-s", serial, "install", "-r", "-g", apk_path], 600)
        if "Success" in out:
            return True, "설치 성공"
        code = re.search(r"(INSTALL_[A-Z_]+)[^\n]*", out)
        return False, (code.group(0) if code else out.strip())[:400]

    def play_install(self, serial, package, timeout: int = 240):
        """Play 스토어 앱 상세 화면을 열어 '설치' 버튼을 누르고 설치 완료를 기다린다.
        기기 계정이 해당 앱의 테스터로 등록·참여되어 있어야 비공개 트랙 앱이 보인다."""
        import time
        self._pkg(package)
        self._sh(serial, "am", "start", "-a", "android.intent.action.VIEW", "-d", f"market://details?id={package}", "com.android.vending")
        deadline, tapped = time.monotonic() + timeout, False
        while time.monotonic() < deadline:
            if self.installed_version(serial, package):
                self.key(serial, "HOME")
                return True, "Play 스토어에서 설치됨"
            xml = self.dump_ui(serial)
            if not tapped:
                m = re.search(r'(?:text|content-desc)="(?:설치|Install|업데이트|Update)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    self.tap(serial, (x1 + x2) // 2, (y1 + y2) // 2)
                    tapped = True
                elif re.search(r"찾을 수 없|not found|isn't available|사용할 수 없", xml):
                    self.key(serial, "HOME")
                    return False, "Play 스토어에서 앱을 찾을 수 없음(테스터 등록·참여 여부 확인 필요)"
            time.sleep(3)
        self.key(serial, "HOME")
        return False, "Play 스토어 설치 시간 초과" if tapped else "Play 스토어에서 설치 버튼을 찾지 못함(테스터 등록·참여 여부 확인 필요)"

    def uninstall(self, serial, package):
        out = self._run(["-s", serial, "uninstall", self._pkg(package)], 120)
        return "Success" in out, out.strip()[:300]

    def installed_version(self, serial, package):
        out = self._sh(serial, "dumpsys", "package", self._pkg(package))
        m = re.search(r"versionName=(\S+)", out)
        return m.group(1) if m else None

    def _launcher(self, serial, package) -> str | None:
        out = self._sh(serial, "cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", package)
        comp = [l.strip() for l in out.splitlines() if "/" in l and package in l]
        return comp[-1] if comp else None

    def launch(self, serial, package):
        comp = self._launcher(serial, self._pkg(package))
        if not comp:
            return {"ok": False, "total_ms": None, "message": "실행 가능한 런처 액티비티를 찾지 못함"}
        out = self._sh(serial, "am", "start", "-W", "-n", comp, timeout=90)
        total = re.search(r"TotalTime:\s*(\d+)", out)
        ok = "Error" not in out and ("Status: ok" in out or "Warning: Activity not started" in out or bool(total))
        return {"ok": ok, "total_ms": int(total.group(1)) if total and "LaunchState: COLD" in out else
                (int(total.group(1)) if total and "LaunchState" not in out else None),
                "message": "" if ok else out.strip()[-300:]}

    def stop(self, serial, package):
        self._sh(serial, "am", "force-stop", self._pkg(package))

    def foreground_package(self, serial):
        out = self._sh(serial, "dumpsys", "activity", "activities")
        m = re.search(r"(?:mResumedActivity|topResumedActivity|ResumedActivity)[^\n]*?\s([\w.]+)/", out)
        if m:
            return m.group(1)
        m = re.search(r"mCurrentFocus=Window\{[^}]*\s([\w.]+)/", self._sh(serial, "dumpsys", "window"))
        return m.group(1) if m else ""

    def pid_of(self, serial, package):
        out = self._sh(serial, "pidof", self._pkg(package)).strip()
        return int(out.split()[0]) if out and out.split()[0].isdigit() else None

    # ----- 화면 / 입력 -----
    def screenshot(self, serial):
        data = self._run(["-s", serial, "exec-out", "screencap", "-p"], 40, binary=True)
        if not data.startswith(b"\x89PNG"):
            raise ProviderError("스크린샷을 가져오지 못했습니다.")
        return data

    def dump_ui(self, serial):
        out = self._run(["-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"], 40)
        start, end = out.find("<?xml"), out.rfind("</hierarchy>")
        if start == -1 or end == -1:
            self._sh(serial, "uiautomator", "dump", "/sdcard/gat_ui.xml", timeout=40)
            out = self._sh(serial, "cat", "/sdcard/gat_ui.xml")
            start, end = out.find("<?xml"), out.rfind("</hierarchy>")
            if start == -1 or end == -1:
                return "<hierarchy/>"
        return out[start:end + len("</hierarchy>")]

    def tap(self, serial, x, y):
        self._sh(serial, "input", "tap", str(int(x)), str(int(y)))

    def input_text(self, serial, text):
        safe = re.sub(r"[^A-Za-z0-9@._\-+]", lambda m: "%s" if m.group(0) == " " else "", text)
        if safe != text.replace(" ", "%s"):
            # 특수문자·한글은 input text로 입력할 수 없어 제외된다(시나리오 결과에 그대로 반영됨)
            pass
        self._sh(serial, "input", "text", safe)

    def swipe(self, serial, direction):
        m = re.search(r"(\d+)x(\d+)", self._static.get(serial, {}).get("resolution", "") or self._sh(serial, "wm", "size"))
        w, h = (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)
        cx, cy = w // 2, h // 2
        paths = {"down": (cx, int(h * .7), cx, int(h * .3)), "up": (cx, int(h * .3), cx, int(h * .7)),
                 "left": (int(w * .8), cy, int(w * .2), cy), "right": (int(w * .2), cy, int(w * .8), cy)}
        x1, y1, x2, y2 = paths.get(direction, paths["down"])
        self._sh(serial, "input", "swipe", str(x1), str(y1), str(x2), str(y2), "300")

    def key(self, serial, name):
        self._sh(serial, "input", "keyevent", {"HOME": "KEYCODE_HOME", "BACK": "KEYCODE_BACK"}[name])

    def set_rotation(self, serial, landscape):
        if landscape is None:
            self._sh(serial, "settings", "put", "system", "accelerometer_rotation", "1")
            return
        self._sh(serial, "settings", "put", "system", "accelerometer_rotation", "0")
        self._sh(serial, "settings", "put", "system", "user_rotation", "1" if landscape else "0")

    # ----- 로그 / 성능 -----
    def logcat_clear(self, serial):
        self._run(["-s", serial, "logcat", "-b", "main,crash,system", "-c"], 30)

    def logcat_dump(self, serial):
        return self._run(["-s", serial, "logcat", "-b", "main,crash,system", "-d", "-v", "threadtime", "*:W"], 60)[-400000:]

    def metrics(self, serial, package):
        self._pkg(package)
        out = {}
        mem = re.search(r"TOTAL(?: PSS)?:?\s+(\d+)", self._sh(serial, "dumpsys", "meminfo", package))
        if mem:
            out["memory_mb"] = int(mem.group(1)) / 1024
        for line in self._sh(serial, "dumpsys", "cpuinfo").splitlines():
            if package in line:
                m = re.search(r"([\d.]+)%", line)
                if m:
                    out["cpu_percent"] = float(m.group(1))
                    break
        disk = self._sh(serial, "dumpsys", "diskstats")
        try:
            names = json.loads(re.search(r"Package Names:\s*(\[.*?\])", disk).group(1))
            idx = names.index(package)
            total = 0
            for label in ("App Sizes", "App Data Sizes", "Cache Sizes"):
                arr = json.loads(re.search(label + r":\s*(\[.*?\])", disk).group(1))
                total += int(arr[idx])
            out["storage_mb"] = total / 1024 / 1024
        except (AttributeError, ValueError, IndexError):
            pass
        temp = re.search(r"temperature:\s*(\d+)", self._sh(serial, "dumpsys", "battery"))
        if temp:
            out["temperature_c"] = int(temp.group(1)) / 10
        return out

    def permissions(self, serial, package):
        out = self._sh(serial, "dumpsys", "package", self._pkg(package))
        requested = re.findall(r"^\s+(android\.permission\.[A-Z_]+)\s*$", out, re.M)
        granted = re.findall(r"(android\.permission\.[A-Z_]+): granted=true", out)
        return {"requested": sorted(set(requested)), "granted": sorted(set(granted))}

    def set_network(self, serial, enabled):
        if ":" in serial:  # TCP(LAN) 연결 기기는 네트워크를 끄면 ADB 연결이 끊어진다
            return False
        state = "enable" if enabled else "disable"
        self._sh(serial, "svc", "wifi", state)
        self._sh(serial, "svc", "data", state)
        return True

    # ----- 장비 관리 -----
    def reboot(self, serial):
        self._run(["-s", serial, "reboot"], 30)

    def reconnect(self, serial):
        if ":" in serial:
            self._run(["disconnect", serial], 20)
            return self._run(["connect", serial], 20).strip()
        return self._run(["-s", serial, "reconnect"], 20).strip() or "재연결 요청"

    def push_file(self, serial, local_path, name):
        safe = re.sub(r"[^A-Za-z0-9._\-]", "_", os.path.basename(name)) or "file"
        target = f"/sdcard/Download/{safe}"
        out = self._run(["-s", serial, "push", local_path, target], 600)
        if "error" in out.lower() and "pushed" not in out:
            raise ProviderError(out.strip()[:300])
        return target

    def restart_server(self) -> None:
        """ADB 서버 오류 복구."""
        self._run(["kill-server"], 20)
        self._run(["start-server"], 30)
