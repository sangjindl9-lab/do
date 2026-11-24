"""system_settings 테이블 접근. 비밀값은 암호화 저장하고 조회 시 마스킹한다."""
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import SystemSetting
from ..security import decrypt, encrypt

# key: (기본값, 비밀 여부, 설명)
DEFAULTS: dict[str, tuple[str, bool, str]] = {
    "site.name": ("구글자동테스터", False, "서비스명"),
    "site.support_email": ("", False, "고객지원 이메일"),
    "site.default_locale": ("ko", False, "기본 언어"),
    "site.locales": ("ko,en", False, "지원 언어(쉼표 구분)"),
    "pg.provider": ("toss", False, "PG사"),
    "pg.mode": ("disabled", False, "disabled | mock | test | live"),
    "pg.toss.client_key": ("", False, "토스페이먼츠 Client Key"),
    "pg.toss.secret_key": ("", True, "토스페이먼츠 Secret Key"),
    "smtp.host": ("", False, "SMTP 호스트"),
    "smtp.port": ("587", False, "SMTP 포트"),
    "smtp.user": ("", False, "SMTP 사용자"),
    "smtp.password": ("", True, "SMTP 비밀번호"),
    "smtp.from": ("", False, "발신 주소"),
    "smtp.tls": ("starttls", False, "starttls | ssl | none"),
    "ai.provider": ("none", False, "none | openai | claude | gemini | local | custom"),
    "ai.api_key": ("", True, "AI API 키"),
    "ai.model": ("", False, "AI 모델명"),
    "ai.base_url": ("", False, "로컬/사용자 지정 AI 서버 주소"),
    "google.client_id": ("", False, "Google OAuth Client ID"),
    "google.client_secret": ("", True, "Google OAuth Client Secret"),
    "storage.kind": ("volume", False, "volume (영구 볼륨)"),
    "limits.max_plans_per_device": ("3", False, "기기 1대가 동시에 맡는 검사 계획 수"),
    "limits.max_jobs_per_agent": ("20", False, "에이전트 1대 동시 실행 작업 수"),
    "limits.job_timeout_sec": ("1800", False, "검사 작업 타임아웃(초)"),
    "limits.job_max_attempts": ("3", False, "검사 작업 최대 시도 횟수"),
    "limits.device_offline_replace_min": ("30", False, "오프라인 기기 대체 배정 기준(분)"),
    "limits.temp_overheat": ("45", False, "과열 판정 온도(℃)"),
    "limits.storage_low_mb": ("1024", False, "저장공간 부족 기준(MB)"),
    "retention.days": ("180", False, "검사 데이터 보존기간(일)"),
    "retention.cleanup_app_after_test": ("1", False, "검사 종료 후 기기에서 대상 앱 삭제"),
    "agent.latest_version": ("1.0.0", False, "에이전트 최신 버전"),
    "agent.token_days": ("90", False, "에이전트 인증키 유효기간(일)"),
}


def get(db: Session, key: str) -> str:
    row = db.get(SystemSetting, key)
    default, secret, _ = DEFAULTS.get(key, ("", False, ""))
    if row is None:
        return default
    return decrypt(row.value) if row.is_secret else (row.value or "")


def get_int(db: Session, key: str) -> int:
    try:
        return int(get(db, key))
    except ValueError:
        return int(DEFAULTS[key][0])


def put(db: Session, key: str, value: str) -> None:
    secret = DEFAULTS.get(key, ("", False, ""))[1]
    row = db.get(SystemSetting, key)
    stored = encrypt(value) if secret else value
    if row is None:
        db.add(SystemSetting(key=key, value=stored, is_secret=secret))
    else:
        row.value, row.is_secret, row.updated_at = stored, secret, utcnow()


def masked_view(db: Session, prefix: str = "") -> list[dict]:
    out = []
    for key, (default, secret, desc) in DEFAULTS.items():
        if prefix and not key.startswith(prefix):
            continue
        val = get(db, key)
        out.append({"key": key, "description": desc, "is_secret": secret,
                    "value": "" if secret else val, "is_set": bool(val),
                    "hint": (val[:4] + "****") if secret and val else ""})
    return out


def payment_state(db: Session) -> dict:
    mode = get(db, "pg.mode")
    provider = get(db, "pg.provider")
    client_key = get(db, "pg.toss.client_key")
    has_keys = bool(client_key and get(db, "pg.toss.secret_key"))
    enabled = mode == "mock" or (mode in ("test", "live") and has_keys)
    return {"provider": "mock" if mode == "mock" else provider, "mode": mode, "enabled": enabled,
            "client_key": client_key if mode in ("test", "live") else "", "has_keys": has_keys}


def smtp_configured(db: Session) -> bool:
    return bool(get(db, "smtp.host") and get(db, "smtp.from"))
