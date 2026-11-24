"""환경변수 기반 설정. 비밀값은 코드에 두지 않는다."""
import base64
import hashlib
import os
import secrets


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    ENV = _env("APP_ENV", "development")
    DATABASE_URL = _env("DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/gat_dev")
    SECRET_KEY = _env("SECRET_KEY") or secrets.token_urlsafe(48)
    SECRET_KEY_IS_EPHEMERAL = not _env("SECRET_KEY")
    ENCRYPTION_KEY = _env("ENCRYPTION_KEY")
    STORAGE_DIR = _env("STORAGE_DIR", "/data")
    PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL").rstrip("/")
    ADMIN_USERNAME = _env("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
    ADMIN_EMAIL = _env("ADMIN_EMAIL", "admin@localhost")
    ACCESS_TOKEN_MINUTES = int(_env("ACCESS_TOKEN_MINUTES", "30"))
    REFRESH_TOKEN_DAYS = int(_env("REFRESH_TOKEN_DAYS", "14"))
    MAX_APK_MB = int(_env("MAX_APK_MB", "300"))
    RUN_SCHEDULER = _env("RUN_SCHEDULER", "1") == "1"
    RATE_LIMIT_PER_MIN = int(_env("RATE_LIMIT_PER_MIN", "1200"))
    FRONTEND_DIST = _env("FRONTEND_DIST", os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
    AGENT_DOWNLOAD_REPO = _env("AGENT_DOWNLOAD_REPO", "sangjindl9-lab/do")

    @property
    def sqlalchemy_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @property
    def fernet_key(self) -> bytes:
        src = self.ENCRYPTION_KEY or self.SECRET_KEY
        return base64.urlsafe_b64encode(hashlib.sha256(src.encode()).digest())


settings = Settings()
