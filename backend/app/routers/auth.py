import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..deps import client_ip, current_user, rate_limit
from ..models import Customer, LoginHistory, Role, Session as UserSession, TestPlan, User, UserToken
from ..security import (hash_password, make_access_token, new_token, password_problem, sha256_hex, sign_path,
                        check_path_signature, verify_password)
from ..services import settings_store
from ..services.audit import audit
from ..services.notifications import notify

router = APIRouter(prefix="/api", tags=["auth"])
MAX_FAILS, LOCK_MINUTES, ROTATION_GRACE_SEC = 5, 15, 60


def base_url(request: Request) -> str:
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


def user_view(user: User) -> dict:
    c = user.customer
    return {"id": user.id, "email": user.email, "username": user.username, "name": user.name, "role": user.role.code,
            "role_name": user.role.name, "is_staff": user.role.is_staff, "locale": user.locale,
            "permissions": [p.code for p in user.role.permissions], "email_verified": user.email_verified,
            "must_change_password": user.must_change_password,
            "customer": {"id": c.id, "kind": c.kind, "company": c.company, "phone": c.phone,
                         "business_no": c.business_no} if c else None}


def issue_session(db: Session, user: User, request: Request) -> dict:
    refresh, refresh_hash = new_token(40)
    db.add(UserSession(user_id=user.id, refresh_hash=refresh_hash, ip=client_ip(request),
                       user_agent=request.headers.get("user-agent", "")[:300],
                       expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_DAYS)))
    return {"access_token": make_access_token(user.id, user.role.code), "refresh_token": refresh,
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60, "user": user_view(user)}


def make_user_token(db: Session, user: User, purpose: str, hours: int) -> str:
    db.execute(update(UserToken).where(UserToken.user_id == user.id, UserToken.purpose == purpose,
                                       UserToken.used_at.is_(None)).values(used_at=utcnow()))
    plain, hashed = new_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=hashed, expires_at=utcnow() + timedelta(hours=hours)))
    return plain


def take_user_token(db: Session, token: str, purpose: str) -> User:
    row = db.scalar(select(UserToken).where(UserToken.token_hash == sha256_hex(token), UserToken.purpose == purpose)
                    .with_for_update(of=UserToken))
    if not row or row.used_at or row.expires_at < utcnow():
        raise HTTPException(400, "유효하지 않거나 만료된 링크입니다.")
    row.used_at = utcnow()
    return db.get(User, row.user_id)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str = Field(min_length=1, max_length=120)
    kind: str = "individual"
    company: str = ""
    phone: str = ""
    locale: str = "ko"
    agree_terms: bool


@router.post("/auth/register", dependencies=[Depends(rate_limit(10, "register"))])
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not body.agree_terms:
        raise HTTPException(400, "이용약관 및 개인정보처리방침에 동의해야 합니다.")
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    email = body.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(409, "이미 가입된 이메일입니다.")
    kind = "business" if body.kind == "business" else "individual"
    role = db.scalar(select(Role).where(Role.code == ("business" if kind == "business" else "customer")))
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), role_id=role.id,
                locale=body.locale if body.locale in ("ko", "en") else "ko")
    db.add(user)
    db.flush()
    db.add(Customer(user_id=user.id, kind=kind, company=body.company.strip()[:160], phone=body.phone.strip()[:40]))
    token = make_user_token(db, user, "verify_email", 48)
    notify(db, user.id, "signup", web=True, email=True)
    notify(db, user.id, "verify_email", {"link": f"{base_url(request)}/verify-email?token={token}"}, web=False)
    db.commit()
    db.refresh(user)
    return {"ok": True, "email_verification_required": settings_store.smtp_configured(db),
            **issue_session_commit(db, user, request)}


def issue_session_commit(db, user, request):
    data = issue_session(db, user, request)
    db.commit()
    return data


class TokenIn(BaseModel):
    token: str


@router.post("/auth/verify-email")
def verify_email(body: TokenIn, db: Session = Depends(get_db)):
    user = take_user_token(db, body.token, "verify_email")
    user.email_verified = True
    db.commit()
    return {"ok": True}


@router.post("/auth/resend-verification", dependencies=[Depends(rate_limit(5, "resend"))])
def resend_verification(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.email_verified:
        return {"ok": True}
    token = make_user_token(db, user, "verify_email", 48)
    notify(db, user.id, "verify_email", {"link": f"{base_url(request)}/verify-email?token={token}"}, web=False)
    db.commit()
    return {"ok": True, "smtp_configured": settings_store.smtp_configured(db)}


class LoginIn(BaseModel):
    identifier: str
    password: str


@router.post("/auth/login", dependencies=[Depends(rate_limit(20, "login"))])
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ident = body.identifier.strip().lower()
    user = db.scalar(select(User).where(or_(func.lower(User.email) == ident, func.lower(User.username) == ident))
                     .with_for_update(of=User))
    ip, ua = client_ip(request), request.headers.get("user-agent", "")[:300]

    def record(success: bool, reason: str = ""):
        db.add(LoginHistory(user_id=user.id if user else None, identifier=ident[:255], ip=ip, user_agent=ua,
                            success=success, reason=reason))

    if not user or user.deleted_at or not user.is_active:
        record(False, "unknown_or_inactive")
        db.commit()
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    if user.locked_until and user.locked_until > utcnow():
        record(False, "locked")
        db.commit()
        raise HTTPException(423, "로그인 시도 초과로 계정이 잠겼습니다. 잠시 후 다시 시도해 주세요.")
    if not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILS:
            user.locked_until, user.failed_logins = utcnow() + timedelta(minutes=LOCK_MINUTES), 0
        record(False, "bad_password")
        db.commit()
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, utcnow()
    record(True)
    data = issue_session(db, user, request)
    db.commit()
    return data


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/auth/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    row = db.scalar(select(UserSession).where(UserSession.refresh_hash == sha256_hex(body.refresh_token)).with_for_update(of=UserSession))
    now = utcnow()
    # 갱신 토큰 회전: 교체된 토큰은 60초 동안만 재사용을 허용한다(여러 탭·새로고침 중 경합 대비).
    if not row or row.revoked_at or row.expires_at < now or (row.rotated_at and row.rotated_at < now - timedelta(seconds=ROTATION_GRACE_SEC)):
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해 주세요.")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "사용할 수 없는 계정입니다.")
    row.rotated_at = row.rotated_at or now
    data = issue_session(db, user, request)
    db.commit()
    return data


@router.post("/auth/logout")
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    db.execute(update(UserSession).where(UserSession.refresh_hash == sha256_hex(body.refresh_token),
                                         UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    db.commit()
    return {"ok": True}


class ForgotIn(BaseModel):
    email: EmailStr


@router.post("/auth/forgot", dependencies=[Depends(rate_limit(5, "forgot"))])
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower(), User.is_active.is_(True)))
    if user:
        token = make_user_token(db, user, "reset_password", 1)
        notify(db, user.id, "reset_password", {"link": f"{base_url(request)}/reset-password?token={token}"}, web=False)
        db.commit()
    # 가입 여부를 노출하지 않는다
    return {"ok": True, "smtp_configured": settings_store.smtp_configured(db)}


class ResetIn(BaseModel):
    token: str
    password: str


def revoke_sessions(db: Session, user_id: int):
    db.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


@router.post("/auth/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    user = take_user_token(db, body.token, "reset_password")
    user.password_hash, user.failed_logins, user.locked_until = hash_password(body.password), 0, None
    user.must_change_password = False
    revoke_sessions(db, user.id)
    db.commit()
    return {"ok": True}


class ChangePwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(body: ChangePwIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다.")
    if problem := password_problem(body.new_password):
        raise HTTPException(400, problem)
    user.password_hash, user.must_change_password = hash_password(body.new_password), False
    revoke_sessions(db, user.id)
    audit(db, user.id, "auth.change_password", "user", user.id, ip=client_ip(request))
    data = issue_session(db, user, request)
    db.commit()
    return data


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_view(user)


class MeIn(BaseModel):
    name: str | None = None
    locale: str | None = None
    company: str | None = None
    phone: str | None = None
    business_no: str | None = None


@router.patch("/me")
def update_me(body: MeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip()[:120]
    if body.locale in ("ko", "en"):
        user.locale = body.locale
    if user.customer:
        for field in ("company", "phone", "business_no"):
            value = getattr(body, field)
            if value is not None:
                setattr(user.customer, field, value.strip()[:160])
    db.commit()
    return user_view(user)


@router.get("/me/logins")
def my_logins(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(LoginHistory).where(LoginHistory.user_id == user.id).order_by(LoginHistory.id.desc()).limit(30))
    return [{"at": r.created_at, "ip": r.ip, "user_agent": r.user_agent, "success": r.success, "reason": r.reason} for r in rows]


class WithdrawIn(BaseModel):
    password: str


@router.post("/me/withdraw")
def withdraw(body: WithdrawIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """회원 탈퇴: 개인정보를 즉시 익명화한다. 진행 중인 검사가 있으면 먼저 종료해야 한다."""
    if user.role.is_staff:
        raise HTTPException(400, "관리자 계정은 탈퇴할 수 없습니다.")
    if user.password_hash and not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "비밀번호가 올바르지 않습니다.")
    if user.customer and db.scalar(select(TestPlan.id).where(TestPlan.customer_id == user.customer.id,
                                                             TestPlan.status.in_(["waiting_devices", "scheduled", "running", "paused"])).limit(1)):
        raise HTTPException(400, "진행 중인 검사가 있습니다. 검사 종료 또는 환불 처리 후 탈퇴할 수 있습니다.")
    audit(db, user.id, "user.withdraw", "user", user.id, ip=client_ip(request))
    user.email, user.username, user.name = f"deleted-{user.id}@deleted.invalid", None, "탈퇴회원"
    user.password_hash, user.google_sub, user.is_active, user.deleted_at = None, None, False, utcnow()
    if user.customer:
        user.customer.company = user.customer.phone = user.customer.business_no = ""
    revoke_sessions(db, user.id)
    db.commit()
    return {"ok": True}


# ---------------- Google OAuth (인증정보 등록 시 활성화) ----------------
@router.get("/auth/google/status")
def google_status(db: Session = Depends(get_db)):
    return {"enabled": bool(settings_store.get(db, "google.client_id") and settings_store.get(db, "google.client_secret"))}


@router.get("/auth/google/start")
def google_start(request: Request, db: Session = Depends(get_db)):
    client_id = settings_store.get(db, "google.client_id")
    if not client_id or not settings_store.get(db, "google.client_secret"):
        raise HTTPException(503, "Google 로그인이 설정되지 않았습니다.")
    nonce = secrets.token_urlsafe(16)
    state = f"{nonce}.{sign_path('oauth:' + nonce, 600)}"
    query = urlencode({"client_id": client_id, "redirect_uri": f"{base_url(request)}/api/auth/google/callback",
                       "response_type": "code", "scope": "openid email profile", "state": state, "prompt": "select_account"})
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + query)


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    try:
        nonce, sig = state.split(".", 1)
        parts = dict(p.split("=") for p in sig.split("&"))
        ok = check_path_signature("oauth:" + nonce, int(parts["exp"]), parts["sig"])
    except (ValueError, KeyError):
        ok = False
    if not ok or not code:
        return RedirectResponse("/login?error=oauth_state")
    try:
        with httpx.Client(timeout=20) as client:
            tok = client.post("https://oauth2.googleapis.com/token", data={
                "code": code, "client_id": settings_store.get(db, "google.client_id"),
                "client_secret": settings_store.get(db, "google.client_secret"),
                "redirect_uri": f"{base_url(request)}/api/auth/google/callback", "grant_type": "authorization_code"})
            tok.raise_for_status()
            info = client.get("https://openidconnect.googleapis.com/v1/userinfo",
                              headers={"Authorization": f"Bearer {tok.json()['access_token']}"})
            info.raise_for_status()
            profile = info.json()
    except (httpx.HTTPError, KeyError):
        return RedirectResponse("/login?error=oauth_failed")
    if not profile.get("email") or not profile.get("email_verified"):
        return RedirectResponse("/login?error=oauth_email")
    email = profile["email"].lower()
    user = db.scalar(select(User).where(or_(User.google_sub == profile["sub"], func.lower(User.email) == email)))
    if user is None:
        role = db.scalar(select(Role).where(Role.code == "customer"))
        user = User(email=email, name=profile.get("name", ""), role_id=role.id, email_verified=True, google_sub=profile["sub"])
        db.add(user)
        db.flush()
        db.add(Customer(user_id=user.id))
        notify(db, user.id, "signup")
        db.commit()
        db.refresh(user)
    elif not user.is_active or user.role.is_staff:
        return RedirectResponse("/login?error=oauth_denied")
    user.google_sub, user.email_verified, user.last_login_at = profile["sub"], True, utcnow()
    db.add(LoginHistory(user_id=user.id, identifier=email, ip=client_ip(request), success=True, reason="google"))
    data = issue_session(db, user, request)
    db.commit()
    # 토큰은 URL fragment로 전달되어 서버 로그에 남지 않는다
    return RedirectResponse(f"/oauth-complete#refresh_token={data['refresh_token']}")
