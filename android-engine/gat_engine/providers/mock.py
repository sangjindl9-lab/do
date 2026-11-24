"""Mock ADB: 실물 장비 없이 전체 작업 흐름을 검증하기 위한 모의 장비.
이 Provider로 만든 결과는 서버에서 is_mock=True로만 저장되어 실제 검사 결과와 섞이지 않는다."""
import struct
import zlib

from ..provider import DeviceInfo, DeviceProvider, ProviderError


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(row * height, 9)) + chunk(b"IEND", b""))


UI_XML = ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
          '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="{pkg}" content-desc="" bounds="[0,0][1080,2400]">'
          '<node index="0" text="MOCK 화면" resource-id="{pkg}:id/title" class="android.widget.TextView" package="{pkg}" content-desc="" bounds="[40,200][1040,320]"/>'
          '<node index="1" text="" resource-id="{pkg}:id/input" class="android.widget.EditText" package="{pkg}" content-desc="입력" bounds="[40,400][1040,520]"/>'
          '<node index="2" text="확인" resource-id="{pkg}:id/ok" class="android.widget.Button" package="{pkg}" content-desc="" bounds="[40,600][1040,720]"/>'
          '</node></hierarchy>')
CRASH_LOG = ("01-01 00:00:01.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main\n"
             "01-01 00:00:01.000  4242  4242 E AndroidRuntime: Process: {pkg}, PID: 4242\n"
             "01-01 00:00:01.000  4242  4242 E AndroidRuntime: java.lang.NullPointerException: (MOCK) simulated crash\n"
             "01-01 00:00:01.000  4242  4242 E AndroidRuntime: \tat {pkg}.MainActivity.onCreate(MainActivity.kt:42)\n")
ANR_LOG = "01-01 00:00:05.000  1000  1000 E ActivityManager: ANR in {pkg} (MOCK)\nReason: Input dispatching timed out\n"


class MockProvider(DeviceProvider):
    """faults: {serial: 'crash' | 'anr' | 'install_fail' | 'offline' | 'adb_error' | 'overheat' | 'low_storage'}"""
    name = "mock"

    def __init__(self, count: int = 20, prefix: str = "MOCK", faults: dict | None = None):
        self.serials = [f"{prefix}{i:04d}" for i in range(1, count + 1)]
        self.faults = dict(faults or {})
        self.state = {s: {"installed": {}, "running": set(), "front": "launcher", "log": "", "net": True} for s in self.serials}

    def _dev(self, serial):
        if serial not in self.state or self.faults.get(serial) == "offline":
            raise ProviderError("device offline")
        if self.faults.get(serial) == "adb_error":
            raise ProviderError("(MOCK) adb server error")
        return self.state[serial]

    def list_serials(self):
        return {s: ("offline" if self.faults.get(s) == "offline" else "device") for s in self.serials}

    def describe(self, serial, packages):
        idx = self.serials.index(serial)
        fault = self.faults.get(serial)
        info = DeviceInfo(serial=serial, state=self.list_serials()[serial], manufacturer="MockMaker", model="Mock S20",
                          android_version=("13", "12", "11")[idx % 3], sdk=(33, 31, 30)[idx % 3], cpu="mock-soc",
                          ram_mb=8192, storage_total_mb=110000, storage_free_mb=300 if fault == "low_storage" else 64000,
                          battery=100, temperature=52.0 if fault == "overheat" else 31.5, resolution="1080x2400", network="wifi")
        if info.state == "device":
            info.installed = {p: v for p, v in self.state[serial]["installed"].items() if p in packages}
        return info

    def install(self, serial, apk_path):
        dev = self._dev(serial)
        if self.faults.get(serial) == "install_fail":
            return False, "INSTALL_FAILED_INSUFFICIENT_STORAGE (MOCK)"
        dev["installed"][self._pending_pkg] = self._pending_version
        return True, "설치 성공 (MOCK)"

    # 엔진은 payload 기준으로 설치하므로, 모의 장비는 어떤 패키지를 설치하는지 미리 알려준다
    _pending_pkg, _pending_version = "", ""

    def prepare(self, package: str, version: str) -> None:
        self._pending_pkg, self._pending_version = package, version

    def uninstall(self, serial, package):
        dev = self._dev(serial)
        dev["running"].discard(package)
        return dev["installed"].pop(package, None) is not None, "Success (MOCK)"

    def installed_version(self, serial, package):
        return self._dev(serial)["installed"].get(package)

    def launch(self, serial, package):
        dev = self._dev(serial)
        if package not in dev["installed"]:
            return {"ok": False, "total_ms": None, "message": "앱이 설치되어 있지 않음 (MOCK)"}
        fault = self.faults.get(serial)
        if fault == "crash":
            dev["log"] += CRASH_LOG.format(pkg=package)
            dev["running"].discard(package)
            return {"ok": True, "total_ms": 400, "message": ""}
        if fault == "anr":
            dev["log"] += ANR_LOG.format(pkg=package)
        dev["running"].add(package)
        dev["front"] = package
        return {"ok": True, "total_ms": 350 + self.serials.index(serial) * 7, "message": ""}

    def stop(self, serial, package):
        dev = self._dev(serial)
        dev["running"].discard(package)
        if dev["front"] == package:
            dev["front"] = "launcher"

    def foreground_package(self, serial):
        return self._dev(serial)["front"]

    def pid_of(self, serial, package):
        return 4242 if package in self._dev(serial)["running"] else None

    def screenshot(self, serial):
        self._dev(serial)
        shade = 40 + (self.serials.index(serial) * 9) % 160
        return _png(108, 240, (shade, 90, 200 - shade))

    def dump_ui(self, serial):
        dev = self._dev(serial)
        return UI_XML.format(pkg=dev["front"]) if dev["front"] != "launcher" else "<hierarchy/>"

    def tap(self, serial, x, y):
        self._dev(serial)

    def input_text(self, serial, text):
        self._dev(serial)

    def swipe(self, serial, direction):
        self._dev(serial)

    def key(self, serial, name):
        dev = self._dev(serial)
        if name == "HOME":
            dev["front"] = "launcher"

    def set_rotation(self, serial, landscape):
        self._dev(serial)

    def logcat_clear(self, serial):
        self._dev(serial)["log"] = ""

    def logcat_dump(self, serial):
        return self._dev(serial)["log"]

    def metrics(self, serial, package):
        idx = self.serials.index(serial)
        self._dev(serial)
        return {"cpu_percent": 3.0 + idx % 5, "memory_mb": 120.0 + idx, "storage_mb": 48.0, "temperature_c": 31.5}

    def permissions(self, serial, package):
        return {"requested": ["android.permission.INTERNET"], "granted": ["android.permission.INTERNET"]}

    def set_network(self, serial, enabled):
        self._dev(serial)["net"] = enabled
        return True

    def reboot(self, serial):
        dev = self._dev(serial)
        dev["running"].clear()
        dev["front"] = "launcher"

    def reconnect(self, serial):
        self.faults.pop(serial, None)
        return "connected (MOCK)"

    def push_file(self, serial, local_path, name):
        self._dev(serial)
        return f"/sdcard/Download/{name}"
