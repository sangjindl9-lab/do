import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import settings
from .db import utcnow

_fernet = Fernet(settings.fernet_key)


def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode())
    except ValueError:
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "비밀번호는 8자 이상이어야 합니다."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "비밀번호에는 영문과 숫자가 모두 포함되어야 합니다."
    return None


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token(nbytes: int = 32) -> tuple[str, str]:
    plain = secrets.token_urlsafe(nbytes)
    return plain, sha256_hex(plain)


def make_access_token(user_id: int, role: str) -> str:
    now = utcnow()
    payload = {"sub": str(user_id), "role": role, "typ": "access", "iat": int(now.timestamp()),
               "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)).timestamp())}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data if data.get("typ") == "access" else None


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode() if value else ""


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def sign_path(path: str, ttl: int = 3600) -> str:
    """파일 다운로드용 단기 서명 URL 파라미터."""
    exp = int(time.time()) + ttl
    sig = hmac.new(settings.SECRET_KEY.encode(), f"{path}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"exp={exp}&sig={sig}"


def check_path_signature(path: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    good = hmac.new(settings.SECRET_KEY.encode(), f"{path}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(good, sig)
