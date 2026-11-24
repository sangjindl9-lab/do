import json
import os
import sys
from dataclasses import asdict, dataclass, field


def default_dir() -> str:
    env = os.environ.get("GAT_AGENT_HOME")
    if env:
        return env
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "GoogleAutoTesterAgent")
    if os.geteuid() == 0 if hasattr(os, "geteuid") else False:
        return "/var/lib/google-auto-tester-agent"
    return os.path.join(os.path.expanduser("~"), ".google-auto-tester-agent")


@dataclass
class Config:
    server_url: str = ""
    agent_id: str = ""
    agent_name: str = ""
    token: str = ""            # 에이전트 인증키(로컬 설정 파일에만 저장, 파일 권한 600)
    token_expires_at: str = ""
    provider: str = "adb"      # adb | mock
    adb_path: str = ""
    mock_devices: int = 20
    mock_faults: dict = field(default_factory=dict)
    max_parallel: int = 20
    heartbeat_sec: int = 15
    appium_url: str = ""       # 선택: Appium 서버 주소
    auto_update: bool = True
    home: str = ""

    @property
    def path(self) -> str:
        return os.path.join(self.home, "config.json")

    @property
    def spool_dir(self) -> str:
        return os.path.join(self.home, "spool")

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.home, "cache")

    @property
    def log_path(self) -> str:
        return os.path.join(self.home, "agent.log")

    def save(self) -> None:
        os.makedirs(self.home, exist_ok=True)
        data = asdict(self)
        data.pop("home")
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)


def load(home: str | None = None) -> Config:
    home = home or default_dir()
    cfg = Config(home=home)
    try:
        with open(cfg.path, encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if hasattr(cfg, k) and k != "home":
                setattr(cfg, k, v)
    except (FileNotFoundError, ValueError):
        pass
    for sub in (cfg.spool_dir, cfg.cache_dir):
        os.makedirs(sub, exist_ok=True)
    return cfg
