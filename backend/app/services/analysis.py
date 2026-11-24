"""오류 분석. 규칙 기반 분석은 항상 동작하고, AI 분석은 인증정보가 있을 때만 선택적으로 수행한다.
AI 결과는 '추정'으로, 기기에서 실제 수집된 오류는 '확인됨'으로 구분 저장한다."""
import hashlib
import json
import re

import httpx
from sqlalchemy.orm import Session

from . import settings_store

RULES = [
    (r"OutOfMemoryError|Failed to allocate", "메모리 부족", "high",
     "이미지·비트맵 해제, 대용량 리스트 페이징, 메모리 누수(LeakCanary) 점검을 권장합니다."),
    (r"NullPointerException", "널 참조", "high", "스택 최상단 호출부의 null 검사와 초기화 순서를 확인하세요."),
    (r"ANR in|Input dispatching timed out|Application Not Responding", "응답 없음(ANR)", "high",
     "메인 스레드의 네트워크·디스크·DB 작업을 백그라운드로 옮기세요."),
    (r"NetworkOnMainThreadException", "메인 스레드 네트워크 호출", "high", "네트워크 호출을 코루틴/백그라운드 스레드로 옮기세요."),
    (r"SecurityException|Permission Denial", "권한 오류", "medium", "런타임 권한 요청 흐름과 매니페스트 권한 선언을 확인하세요."),
    (r"ActivityNotFoundException|ClassNotFoundException|NoClassDefFoundError", "구성요소 누락", "high",
     "매니페스트 등록 및 난독화(ProGuard/R8) keep 규칙을 확인하세요."),
    (r"UnknownHostException|SocketTimeoutException|ConnectException|SSLHandshakeException", "네트워크 오류", "medium",
     "네트워크 장애 시 재시도·오류 안내 화면 처리를 확인하세요."),
    (r"SQLiteException|IllegalStateException.*database|Room", "데이터베이스 오류", "high", "DB 마이그레이션과 스키마 버전을 확인하세요."),
    (r"Resources\$NotFoundException|InflateException", "리소스/레이아웃 오류", "medium", "해상도·언어별 리소스 누락 여부를 확인하세요."),
    (r"IllegalArgumentException|IllegalStateException|IndexOutOfBoundsException|ClassCastException", "로직 예외", "medium",
     "스택 트레이스의 앱 패키지 프레임을 기준으로 입력값 검증을 보강하세요."),
    (r"SIGSEGV|SIGABRT|Fatal signal|native crash", "네이티브 크래시", "critical", "NDK 라이브러리의 ABI 호환성과 심볼 파일을 확인하세요."),
    (r"INSTALL_FAILED_[A-Z_]+", "설치 실패", "critical", "minSdk·ABI·서명·저장공간 조건을 확인하세요."),
]


def signature_of(kind: str, title: str, detail: str) -> str:
    """중복 오류 분류용 서명: 예외 종류 + 앱 스택 상위 프레임에서 숫자/주소를 제거해 해시."""
    exc = re.search(r"([\w.$]+(?:Exception|Error))", f"{title}\n{detail}")
    frames = re.findall(r"at ([\w.$]+)\(", detail)[:3]
    base = "|".join([kind, exc.group(1) if exc else re.sub(r"\d+", "", title)[:80], *frames])
    return hashlib.sha256(base.encode()).hexdigest()[:32]


def analyze_rule(kind: str, title: str, detail: str) -> dict:
    text = f"{title}\n{detail}"
    for pattern, category, severity, advice in RULES:
        if re.search(pattern, text):
            return {"category": category, "severity": severity, "advice": advice, "source": "rule"}
    severity = "high" if kind in ("crash", "anr") else "low"
    return {"category": "미분류", "severity": severity, "advice": "오류 로그의 스택 트레이스를 확인하세요.", "source": "rule"}


def ai_configured(db: Session) -> bool:
    provider = settings_store.get(db, "ai.provider")
    if provider in ("", "none"):
        return False
    if provider in ("local", "custom"):
        return bool(settings_store.get(db, "ai.base_url"))
    return bool(settings_store.get(db, "ai.api_key"))


def _ai_call(db: Session, prompt: str) -> str:
    provider = settings_store.get(db, "ai.provider")
    key, model, base = (settings_store.get(db, "ai.api_key"), settings_store.get(db, "ai.model"),
                        settings_store.get(db, "ai.base_url").rstrip("/"))
    with httpx.Client(timeout=60) as client:
        if provider == "claude":
            res = client.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                              json={"model": model, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]})
            res.raise_for_status()
            return res.json()["content"][0]["text"]
        if provider == "gemini":
            res = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json={"contents": [{"parts": [{"text": prompt}]}]})
            res.raise_for_status()
            return res.json()["candidates"][0]["content"]["parts"][0]["text"]
        # openai / local / custom: OpenAI 호환 chat completions
        url = (base or "https://api.openai.com/v1") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        res = client.post(url, headers=headers, json={"model": model, "messages": [{"role": "user", "content": prompt}]})
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]


def analyze_ai(db: Session, kind: str, title: str, detail: str) -> dict | None:
    """AI 추정 분석. 실패하거나 미설정이면 None (규칙 기반 결과만 사용)."""
    if not ai_configured(db):
        return None
    prompt = ("다음은 Android 앱 실기기 검사에서 수집된 오류 로그입니다. JSON으로만 답하세요: "
              '{"cause": "추정 원인", "severity": "low|medium|high|critical", "advice": "개선 권고"}\n\n'
              f"종류: {kind}\n제목: {title}\n로그:\n{detail[:6000]}")
    try:
        text = _ai_call(db, prompt)
        match = re.search(r"\{.*\}", text, re.S)
        data = json.loads(match.group(0)) if match else {"cause": text[:1000]}
        return {**data, "source": "ai", "note": "AI 추정 결과이며 확인된 사실이 아닙니다."}
    except Exception as exc:  # noqa: BLE001 - AI 실패는 검사 결과에 영향을 주지 않는다
        return {"source": "ai", "error": str(exc)[:200]}


def test_ai(db: Session) -> dict:
    if not ai_configured(db):
        return {"ok": False, "message": "AI 인증정보가 설정되지 않았습니다. 규칙 기반 분석만 동작합니다."}
    try:
        return {"ok": True, "message": _ai_call(db, "연결 확인입니다. 'OK'라고만 답하세요.")[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"AI 연동 실패: {exc}"[:300]}
