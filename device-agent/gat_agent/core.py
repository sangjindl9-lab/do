"""에이전트 본체: 기기 검색 → 하트비트 → 작업 수신·실행 → 결과 전송(실패 시 로컬 보관 후 재전송)."""
import base64
import json
import logging
import os
import platform
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from gat_engine import JobError, run_job, run_scenario
from gat_engine.provider import ProviderError
from gat_engine.providers import AdbProvider, MockProvider

from . import __version__
from .api import ApiError, NetworkError, ServerClient
from .config import Config

log = logging.getLogger("gat.agent")


def make_provider(cfg: Config):
    if cfg.provider == "mock":
        return MockProvider(cfg.mock_devices, faults=cfg.mock_faults)
    return AdbProvider(cfg.adb_path)


class Spool:
    """인터넷 장애 시 결과·스크린샷을 디스크에 보관하고 연결 복구 후 순서대로 동기화한다."""

    def __init__(self, directory: str):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        self.lock = threading.Lock()
        self.seq = 0

    def put(self, kind: str, payload: dict) -> str:
        with self.lock:
            self.seq += 1
            name = f"{int(time.time() * 1000):015d}-{self.seq:05d}-{kind}.json"
        tmp = os.path.join(self.dir, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(self.dir, name))
        return name

    def items(self) -> list[str]:
        return sorted(n for n in os.listdir(self.dir) if n.endswith(".json"))

    def read(self, name: str) -> dict:
        with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
            return json.load(fh)

    def remove(self, name: str) -> None:
        try:
            os.remove(os.path.join(self.dir, name))
        except FileNotFoundError:
            pass


class Agent:
    def __init__(self, cfg: Config, client: ServerClient | None = None, provider=None, sleep=time.sleep, settle: float = 3.0):
        self.cfg = cfg
        self.api = client or ServerClient(cfg.server_url, cfg.token)
        self.provider = provider or make_provider(cfg)
        self.spool = Spool(cfg.spool_dir)
        self.pool = ThreadPoolExecutor(max_workers=max(1, cfg.max_parallel), thread_name_prefix="job")
        self.running: dict[int, dict] = {}      # job_id -> {"serial", "progress", "package", "cancel"}
        self.busy_serials: set[str] = set()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.devices: list[dict] = []
        self.history: list[dict] = []           # 최근 작업 기록(GUI 표시용)
        self.errors: list[dict] = []
        self.connected = False
        self.latest_version = ""
        self.packages: set[str] = set()
        self.sleep, self.settle = sleep, settle
        self.adb_failures = 0
        self.pending_cmds = 0

    # ---------- 상태 기록 ----------
    def _error(self, message: str) -> None:
        log.error(message)
        self.errors.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "message": message})
        del self.errors[:-200]

    def _record(self, job_id: int, serial: str, package: str, status: str, note: str = "") -> None:
        self.history.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "job_id": job_id, "serial": serial,
                             "package": package, "status": status, "note": note})
        del self.history[:-300]

    # ---------- 기기 검색 ----------
    def scan_devices(self) -> list[dict]:
        try:
            serials = self.provider.list_serials()
            self.adb_failures = 0
        except ProviderError as exc:
            self.adb_failures += 1
            self._error(f"기기 검색 실패: {exc}")
            if self.adb_failures >= 3 and hasattr(self.provider, "restart_server"):
                try:
                    self.provider.restart_server()  # ADB 서버 오류 자동 복구
                    self.adb_failures = 0
                    log.info("ADB 서버를 재시작했습니다.")
                except ProviderError as exc2:
                    self._error(f"ADB 서버 재시작 실패: {exc2}")
            return self.devices
        out = []
        for serial, state in serials.items():
            if state != "device":
                out.append({"serial": serial, "state": state})
                continue
            try:
                out.append(self.provider.describe(serial, sorted(self.packages)).to_dict())
            except ProviderError as exc:
                out.append({"serial": serial, "state": "offline"})
                self._error(f"{serial} 정보 수집 실패: {exc}")
        self.devices = out
        return out

    # ---------- 서버 동기화 ----------
    def heartbeat(self) -> dict | None:
        devices = self.scan_devices()
        try:
            res = self.api.heartbeat(__version__, devices, list(self.running))
        except NetworkError as exc:
            if self.connected:
                self._error(f"서버 연결 끊김: {exc}")
            self.connected = False
            return None
        except ApiError as exc:
            self.connected = False
            self._error(f"서버 인증 오류: {exc.message}")
            return None
        if not self.connected:
            log.info("서버 연결됨")
        self.connected = True
        self.latest_version = res.get("latest_version", "")
        for job_id in res.get("cancel_jobs", []):
            if job_id in self.running:
                self.running[job_id]["cancel"] = True
        for cmd in res.get("commands", []):
            with self.lock:
                self.pending_cmds += 1
            self.pool.submit(self._run_command, cmd)
        return res

    def flush_spool(self) -> int:
        """보관된 결과 전송. 서버가 받으면(또는 영구 거부하면) 삭제한다."""
        sent = 0
        for name in self.spool.items():
            item = self.spool.read(name)
            try:
                if name.endswith("-shot.json"):
                    self.api.screenshot(item["job_id"], item["lease_token"], item["label"], base64.b64decode(item["data"]))
                elif name.endswith("-result.json"):
                    self.api.result(item["job_id"], item["body"])
                elif name.endswith("-fail.json"):
                    self.api.fail(item["job_id"], item["lease_token"], item["error"], item["retryable"])
            except NetworkError:
                return sent  # 아직 오프라인: 순서를 지키기 위해 중단
            except ApiError as exc:
                self._error(f"보관 데이터 전송 거부({name}): {exc.message}")  # 임대 만료 등: 재전송해도 받지 않음
            self.spool.remove(name)
            sent += 1
        return sent

    def claim_and_start(self) -> int:
        with self.lock:
            room = self.cfg.max_parallel - len(self.running)
        if room <= 0 or not self.connected:
            return 0
        try:
            jobs = self.api.claim(room)
        except (NetworkError, ApiError) as exc:
            self._error(f"작업 수신 실패: {exc}")
            return 0
        for job in jobs:
            with self.lock:
                self.running[job["id"]] = {"serial": job["serial"], "progress": 0, "package": job["payload"]["package"], "cancel": False}
            self.packages.add(job["payload"]["package"])
            self.pool.submit(self._run_job, job)
        return len(jobs)

    # ---------- 작업 실행 ----------
    def _send(self, kind: str, payload: dict, call) -> None:
        """먼저 디스크에 보관한 뒤 전송한다. 전송에 실패하면 보관분이 남아 나중에 재전송된다."""
        name = self.spool.put(kind, payload)
        try:
            call()
            self.spool.remove(name)
        except NetworkError:
            log.warning("서버 전송 실패: 로컬 보관 (%s)", name)
        except ApiError as exc:
            self.spool.remove(name)
            self._error(f"서버가 데이터를 거부했습니다: {exc.message}")

    def _run_job(self, job: dict) -> None:
        job_id, serial, lease, payload = job["id"], job["serial"], job["lease_token"], job["payload"]
        package = payload["package"]
        state = self.running[job_id]
        apk_path = None

        def on_progress(pct):
            state["progress"] = pct
            if state["cancel"]:
                raise JobError("서버에서 취소된 작업입니다.", retryable=False)
            try:
                self.api.progress(job_id, lease, pct)
            except ApiError as exc:
                if exc.status == 409:
                    raise JobError("임대가 만료되었거나 취소된 작업입니다.", retryable=False) from exc
            except NetworkError:
                pass

        def on_screenshot(label, data):
            body = {"job_id": job_id, "lease_token": lease, "label": label, "data": base64.b64encode(data).decode()}
            self._send("shot", body, lambda: self.api.screenshot(job_id, lease, label, data))

        try:
            apk = payload.get("apk")
            if apk:
                apk_path = os.path.join(self.cfg.cache_dir, f"{apk['sha256']}.apk")
                if not os.path.exists(apk_path):
                    tmp = apk_path + f".{job_id}.part"
                    self.api.download(apk["file_id"], tmp, apk["sha256"])
                    os.replace(tmp, apk_path)
            if isinstance(self.provider, MockProvider):
                self.provider.prepare(package, payload.get("version_name", ""))
            result = run_job(self.provider, serial, payload, apk_path, on_progress, on_screenshot, sleep=self.sleep, settle=self.settle)
            body = {**result, "lease_token": lease, "agent_version": __version__}
            self._send("result", {"job_id": job_id, "body": body}, lambda: self.api.result(job_id, body))
            self._record(job_id, serial, package, result["status"])
        except JobError as exc:
            cancelled = state["cancel"]
            if not cancelled:
                self._send("fail", {"job_id": job_id, "lease_token": lease, "error": str(exc), "retryable": exc.retryable},
                           lambda: self.api.fail(job_id, lease, str(exc), exc.retryable))
            self._record(job_id, serial, package, "cancelled" if cancelled else "error", str(exc))
        except (NetworkError, ApiError) as exc:
            msg = f"APK 다운로드 실패: {exc}"
            self._send("fail", {"job_id": job_id, "lease_token": lease, "error": msg, "retryable": True},
                       lambda: self.api.fail(job_id, lease, msg, True))
            self._record(job_id, serial, package, "error", msg)
        except Exception as exc:  # noqa: BLE001 - 예기치 못한 오류도 서버에 실패로 보고
            log.exception("job %s crashed", job_id)
            msg = f"에이전트 내부 오류: {exc.__class__.__name__}: {exc}"
            self._send("fail", {"job_id": job_id, "lease_token": lease, "error": msg, "retryable": True},
                       lambda: self.api.fail(job_id, lease, msg, True))
            self._record(job_id, serial, package, "error", msg)
        finally:
            with self.lock:
                self.running.pop(job_id, None)
            self.wake_event.set()

    # ---------- 원격 제어(승인된 명령만) ----------
    def _run_command(self, cmd: dict) -> None:
        serial, ctype, params = cmd["serial"], cmd["type"], cmd.get("params") or {}
        ok, message, image = True, "", None
        try:
            p = self.provider
            if ctype == "screenshot":
                image, message = p.screenshot(serial), "스크린샷 저장"
            elif ctype in ("install_apk", "push_file"):
                path = os.path.join(self.cfg.cache_dir, f"{params['sha256']}.bin")
                if not os.path.exists(path):
                    self.api.download(params["file_id"], path, params["sha256"])
                if ctype == "install_apk":
                    if isinstance(p, MockProvider):
                        p.prepare(params.get("package", ""), "remote")
                    ok, message = p.install(serial, path)
                else:
                    message = "전송 완료: " + p.push_file(serial, path, params.get("filename", "file"))
            elif ctype == "uninstall":
                done, out = p.uninstall(serial, params["package"])
                message = "삭제 완료" if done else f"삭제할 앱이 없거나 실패: {out}"
            elif ctype == "launch":
                res = p.launch(serial, params["package"])
                ok, message = res["ok"], res.get("message") or "앱 실행"
            elif ctype == "stop":
                p.stop(serial, params["package"])
                message = "앱 종료"
            elif ctype == "app_version":
                ver = p.installed_version(serial, params["package"])
                message = f"설치 버전: {ver}" if ver else "설치되어 있지 않음"
            elif ctype in ("storage", "status"):
                info = p.describe(serial, [])
                message = json.dumps({k: getattr(info, k) for k in ("state", "battery", "temperature", "storage_total_mb",
                                                                    "storage_free_mb", "network", "android_version")}, ensure_ascii=False)
            elif ctype == "reconnect":
                message = p.reconnect(serial)
            elif ctype == "reboot":
                p.reboot(serial)
                message = "재부팅 요청"
            elif ctype == "run_scenario":
                steps = run_scenario(p, serial, params["package"], params["steps"], sleep=self.sleep)
                ok = all(s["status"] == "passed" for s in steps)
                message = json.dumps([{"name": s["name"], "status": s["status"], "actual": s["actual"]} for s in steps], ensure_ascii=False)
            else:
                ok, message = False, f"승인되지 않은 명령: {ctype}"
        except (ProviderError, NetworkError, ApiError, KeyError) as exc:
            ok, message = False, f"명령 실패: {exc}"
        try:
            self.api.command_result(cmd["id"], ok, message, image)
        except (NetworkError, ApiError) as exc:
            self._error(f"명령 결과 전송 실패: {exc}")
        finally:
            with self.lock:
                self.pending_cmds -= 1

    # ---------- 실행 루프 ----------
    def tick(self) -> None:
        """한 주기: 하트비트 → 보관분 동기화 → 작업 수신."""
        if self.heartbeat() is not None:
            self.flush_spool()
            self.claim_and_start()

    def wait_idle(self, timeout: float = 60) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if not self.running and not self.pending_cmds:
                    return True
            time.sleep(0.05)
        return False

    def _ws_loop(self) -> None:
        """WebSocket으로 서버의 깨우기 신호를 받는다(없어도 주기 폴링으로 동작)."""
        try:
            from websockets.sync.client import connect
        except ImportError:
            return
        url = self.cfg.server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/api/agent/ws"
        while not self.stop_event.is_set():
            try:
                with connect(url, open_timeout=15) as ws:
                    ws.send(json.dumps({"token": self.api.token}))
                    while not self.stop_event.is_set():
                        msg = json.loads(ws.recv(timeout=60))
                        if msg.get("type") in ("wake", "command"):
                            self.wake_event.set()
            except Exception:  # noqa: BLE001 - 자동 재연결
                self.stop_event.wait(10)

    def run_forever(self) -> None:
        log.info("Google Auto Tester Agent %s 시작 (%s, provider=%s)", __version__, self.cfg.server_url, self.cfg.provider)
        threading.Thread(target=self._ws_loop, daemon=True, name="ws").start()
        backoff = self.cfg.heartbeat_sec
        while not self.stop_event.is_set():
            self.tick()
            backoff = self.cfg.heartbeat_sec if self.connected else min(120, backoff * 2)  # 연결 장애 시 지수 백오프 재연결
            self.wake_event.wait(backoff)
            self.wake_event.clear()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()


def enroll(cfg: Config, server_url: str, code: str, client: ServerClient | None = None) -> dict:
    api = client or ServerClient(server_url)
    data = api.enroll(code, socket.gethostname(), f"{platform.system()} {platform.release()}", __version__)
    cfg.server_url, cfg.agent_id, cfg.agent_name = server_url.rstrip("/"), data["agent_id"], data["name"]
    cfg.token, cfg.token_expires_at = data["token"], str(data["expires_at"])
    if data.get("kind") == "mock":
        cfg.provider = "mock"
    cfg.save()
    return data


def rotate_token(cfg: Config, client: ServerClient | None = None) -> None:
    api = client or ServerClient(cfg.server_url, cfg.token)
    data = api.rotate()
    cfg.token, cfg.token_expires_at = data["token"], str(data["expires_at"])
    cfg.save()
