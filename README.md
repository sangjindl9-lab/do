# 구글자동테스터 (Google Auto Tester)

폰팜(Phone Farm Box) 실기기에서 Android 앱을 자동으로 검사하는 유료 SaaS 플랫폼입니다.

> 본 서비스는 **Google의 공식 서비스가 아닌 독립적인 제3자 앱 품질검사 서비스**입니다.
> 검사 기기 수는 실제 검사 기기 수량이며 Google Play 비공개 테스트의 독립적인 참여자 수를 의미하지 않습니다.
> 기기 자동 검사 기록은 인간 테스터 참여로 표시하지 않으며, 프로덕션 승인을 보장하지 않습니다.

## 구성

| 폴더 | 내용 |
| --- | --- |
| `backend/` | FastAPI 서버: 회원·인증, 앱 등록, 주문, 결제(`app/services/payment_providers.py`), 기기 배정, 스케줄러(`app/services/scheduler.py`), 보고서(`app/services/reports.py`), 알림, 관리자 API, Alembic 마이그레이션(`alembic/`) |
| `frontend/` | React + TypeScript + Tailwind: 고객 홈페이지, 고객 대시보드, 관리자 페이지(`/admin`) |
| `android-engine/` | `gat_engine`: Device Provider 인터페이스, 표준 ADB 구현, Mock ADB, 검사 실행기, 시나리오 드라이버 |
| `device-agent/` | `gat_agent`: PC 설치형 프로그램 Google Auto Tester Agent(관리 창, CLI, Windows 서비스) |
| `installers/` | Windows 설치 마법사(Inno Setup), Linux 설치 스크립트·systemd 서비스 |
| `tests/` | 통합 테스트(PostgreSQL + 실제 마이그레이션 + 실제 에이전트 코드 + 모의 장비) |
| `scripts/` | 브라우저 E2E 검증 스크립트 |
| `docs/` | 설명서 일체 |

기술 스택: Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · APScheduler · ReportLab · openpyxl / React 18 · Vite · Tailwind CSS / PySide6 · ADB.
권장안의 Next.js 대신 Vite(React SPA)를 사용했습니다. API 서버 하나가 화면까지 함께 제공해 Railway 서비스 1개 + DB 1개로 운영하기 위함입니다. 작업 대기열은 Redis 없이 PostgreSQL 영속 큐(행 잠금 + 임대 시간)로 구현했습니다.

## 로컬 실행

```bash
# 1) 데이터베이스(PostgreSQL 14+)를 준비하고 환경변수 설정
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/gat
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export ADMIN_PASSWORD='원하는-관리자-비밀번호'
export STORAGE_DIR=./data

# 2) 프론트엔드 빌드
cd frontend && npm ci && npm run build && cd ..

# 3) 마이그레이션 + 서버
cd backend && pip install -r requirements.txt && alembic upgrade head
uvicorn app.main:app --port 8000        # http://localhost:8000 , 관리자 http://localhost:8000/admin
```

Docker: `.env`에 `SECRET_KEY`, `ADMIN_PASSWORD`를 넣고 `docker compose up --build`.

프론트엔드 개발 서버: `cd frontend && npm run dev` (API는 8000번으로 프록시).

## 테스트

```bash
pip install -r backend/requirements.txt pytest websockets
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/gat_test python -m pytest tests -q
# 실행 중인 서버를 실제 브라우저로 검증(Playwright + Chrome 필요)
python scripts/e2e_browser.py --base http://127.0.0.1:8000 --admin-password '...'
```

## 배포 (Railway)

`Dockerfile` + `railway.json` 기준입니다. 서비스 1개(web) + PostgreSQL + 볼륨(`/data`).
필수 환경변수는 `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`, `PUBLIC_BASE_URL`입니다. 자세한 내용은 [docs/deployment.md](docs/deployment.md).

## PC 에이전트

설치 파일은 `agent-v*` 태그를 푸시하면 GitHub Actions가 빌드해 [Releases](https://github.com/sangjindl9-lab/do/releases)에 등록합니다.
설치·인증 방법은 [docs/agent-install.md](docs/agent-install.md), 장비 연결은 [docs/phonefarm-setup.md](docs/phonefarm-setup.md).

## 문서

- [시스템 구성도](docs/architecture.md) · [API 명세](docs/api.md) · [환경변수](docs/deployment.md)
- [관리자 사용설명서](docs/admin-guide.md) · [고객 사용설명서](docs/customer-guide.md)
- [PC 에이전트 설치설명서](docs/agent-install.md) · [폰팜 장비 연결설명서](docs/phonefarm-setup.md)
- [PG 인증정보 등록설명서](docs/pg-setup.md) · [백업 및 복구](docs/backup-restore.md) · [장애 대응 매뉴얼](docs/incident-runbook.md)
- [테스트 실행 결과](docs/test-results.md) · [최종 개발 완료 보고서](docs/final-report.md)

## 라이선스 고지

보고서 PDF에 나눔고딕(SIL Open Font License, `backend/app/assets/fonts/OFL.txt`)을 내장합니다.
화면 디자인 기준은 unslop by Damir Sokolovsky(@heydamir, CC BY 4.0)를 참고했습니다.
