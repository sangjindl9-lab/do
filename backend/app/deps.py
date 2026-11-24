import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, utcnow
from .models import Agent, AgentToken, Customer, User
from .security import decode_access_token, sha256_hex


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:60]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "로그인이 필요합니다.")
    data = decode_access_token(auth[7:].strip())
    if not data:
        raise HTTPException(401, "인증이 만료되었습니다. 다시 로그인해 주세요.")
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active or user.deleted_at:
        raise HTTPException(401, "사용할 수 없는 계정입니다.")
    return user


def current_customer(user: User = Depends(current_user)) -> Customer:
    if not user.customer:
        raise HTTPException(403, "고객 계정만 이용할 수 있습니다.")
    return user.customer


def has_perm(user: User, code: str) -> bool:
    return user.role.is_staff and (user.role.code == "superadmin" or any(p.code == code for p in user.role.permissions))


def require_staff(user: User = Depends(current_user)) -> User:
    if not user.role.is_staff:
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


def require_perm(code: str):
    def dep(user: User = Depends(require_staff)) -> User:
        if not has_perm(user, code):
            raise HTTPException(403, "이 메뉴에 대한 권한이 없습니다.")
        return user
    return dep


def current_agent(request: Request, db: Session = Depends(get_db)) -> Agent:
    """에이전트 전용 인증. 관리자/고객 토큰과 완전히 분리된 인증키를 사용한다."""
    token = request.headers.get("x-agent-token", "")
    return agent_from_token(db, token)


def agent_from_token(db: Session, token: str) -> Agent:
    if not token:
        raise HTTPException(401, "에이전트 인증키가 필요합니다.")
    row = db.scalar(select(AgentToken).where(AgentToken.token_hash == sha256_hex(token)))
    if not row or row.revoked_at or row.expires_at < utcnow():
        raise HTTPException(401, "에이전트 인증키가 유효하지 않거나 만료되었습니다.")
    agent = db.get(Agent, row.agent_id)
    if not agent or agent.status == "revoked":
        raise HTTPException(401, "폐기된 에이전트입니다.")
    return agent


class RateLimiter:
    """IP 단위 고정 창 요청 제한(프로세스 메모리)."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self.hits) > 20000:
            self.hits.clear()
        return True


limiter = RateLimiter()


def rate_limit(limit: int, scope: str):
    def dep(request: Request):
        if settings.ENV == "test":
            return
        if not limiter.allow(f"{scope}:{client_ip(request)}", limit):
            raise HTTPException(429, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
    return dep
