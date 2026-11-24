"""서버 통신(HTTPS). 에이전트 인증키는 X-Agent-Token 헤더로만 전달한다."""
import hashlib

import httpx


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status, self.message = status, message


class NetworkError(Exception):
    """서버에 연결할 수 없음(인터넷 장애 등). 로컬 보관 후 재시도 대상."""


class ServerClient:
    def __init__(self, base_url: str, token: str = "", client: httpx.Client | None = None, allow_http: bool = False):
        base_url = base_url.rstrip("/")
        local = base_url.startswith(("http://localhost", "http://127.0.0.1", "http://testserver"))
        if client is None and not base_url.startswith("https://") and not (local or allow_http):
            raise ValueError("서버 주소는 https:// 로 시작해야 합니다.")
        self.base, self.token = base_url, token
        self.client = client or httpx.Client(timeout=httpx.Timeout(30, read=120))
        self._owns_base = client is None

    def _url(self, path: str) -> str:
        return (self.base if self._owns_base else "") + "/api/agent" + path

    def _call(self, method: str, path: str, **kw):
        headers = {"X-Agent-Token": self.token} if self.token else {}
        try:
            res = self.client.request(method, self._url(path), headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        if res.status_code >= 500:
            raise NetworkError(f"server {res.status_code}")
        if res.status_code >= 400:
            try:
                detail = res.json().get("detail", res.text)
            except ValueError:
                detail = res.text
            raise ApiError(res.status_code, str(detail)[:300])
        return res

    def enroll(self, code: str, hostname: str, os_name: str, version: str) -> dict:
        return self._call("POST", "/enroll", json={"code": code, "hostname": hostname, "os": os_name, "version": version}).json()

    def rotate(self) -> dict:
        return self._call("POST", "/token/rotate").json()

    def heartbeat(self, version: str, devices: list[dict], running_jobs: list[int]) -> dict:
        return self._call("POST", "/heartbeat", json={"version": version, "devices": devices, "running_jobs": running_jobs}).json()

    def claim(self, limit: int) -> list[dict]:
        return self._call("POST", "/jobs/claim", json={"limit": limit}).json()["jobs"]

    def progress(self, job_id: int, lease_token: str, pct: int) -> None:
        self._call("POST", f"/jobs/{job_id}/progress", json={"lease_token": lease_token, "progress": pct})

    def result(self, job_id: int, body: dict) -> dict:
        return self._call("POST", f"/jobs/{job_id}/result", json=body).json()

    def fail(self, job_id: int, lease_token: str, error: str, retryable: bool) -> dict:
        return self._call("POST", f"/jobs/{job_id}/fail", json={"lease_token": lease_token, "error": error[:1900], "retryable": retryable}).json()

    def screenshot(self, job_id: int, lease_token: str, label: str, data: bytes) -> dict:
        return self._call("POST", f"/jobs/{job_id}/screenshot",
                          data={"lease_token": lease_token, "label": label, "sha256": hashlib.sha256(data).hexdigest()},
                          files={"file": ("shot.png", data, "image/png")}).json()

    def download(self, file_id: int, dest: str, sha256: str) -> None:
        """APK 다운로드 + SHA-256 무결성 확인."""
        res = self._call("GET", f"/files/{file_id}")
        if hashlib.sha256(res.content).hexdigest() != sha256:
            raise ApiError(422, "다운로드한 파일의 무결성 검증에 실패했습니다.")
        with open(dest, "wb") as fh:
            fh.write(res.content)

    def command_result(self, cmd_id: int, ok: bool, message: str, image: bytes | None = None) -> None:
        data = {"status": "done" if ok else "failed", "message": message[:3900]}
        files = None
        if image:
            data["sha256"] = hashlib.sha256(image).hexdigest()
            files = {"file": ("shot.png", image, "image/png")}
        self._call("POST", f"/commands/{cmd_id}/result", data=data, files=files)
