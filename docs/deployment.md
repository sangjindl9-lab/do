# 배포 및 환경변수

## Railway 구성

| 항목 | 값 |
| --- | --- |
| 프로젝트 | `google-auto-tester` |
| 서비스 | `web` (GitHub `sangjindl9-lab/do` main 브랜치, Dockerfile 빌드, 푸시 시 자동 배포) |
| 데이터베이스 | PostgreSQL (Railway 템플릿) |
| 볼륨 | `/data` 에 마운트 (APK·스크린샷·보고서·백업) |
| 헬스체크 | `GET /api/health` |
| 시작 명령 | `alembic upgrade head && uvicorn app.main:app` (Dockerfile CMD) |

복제(replica)는 1개로 유지합니다. 에이전트 WebSocket 허브가 프로세스 메모리에 있기 때문입니다(스케줄러는 advisory lock으로 중복 실행을 막아 두었습니다).

## 환경변수

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `DATABASE_URL` | 예 | PostgreSQL 주소. Railway에서는 `${{Postgres.DATABASE_URL}}` |
| `SECRET_KEY` | 예 | 세션 서명 + 비밀 설정 암호화 키. **변경하면 저장된 PG/SMTP/AI 키를 다시 입력해야 합니다** |
| `ADMIN_PASSWORD` | 예 | 최고관리자(`admin`) 비밀번호. 최초 기동 시에만 적용. 비우면 임시 비밀번호가 서버 로그에 1회 출력 |
| `PUBLIC_BASE_URL` | 권장 | 공개 주소(예: `https://xxx.up.railway.app`). 이메일 링크·OAuth 리디렉션·웹훅 주소에 사용 |
| `STORAGE_DIR` | - | 기본 `/data` |
| `ADMIN_USERNAME`, `ADMIN_EMAIL` | - | 기본 `admin`, `admin@localhost` |
| `ENCRYPTION_KEY` | - | 비밀 설정 암호화 전용 키(미설정 시 SECRET_KEY에서 파생) |
| `MAX_APK_MB` | - | APK 크기 제한(기본 300) |
| `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS` | - | 세션 만료(기본 30분 / 14일) |
| `RATE_LIMIT_PER_MIN` | - | IP당 분당 API 요청 한도(기본 1200) |
| `RUN_SCHEDULER` | - | `0`이면 스케줄러 미실행 |
| `AGENT_DOWNLOAD_REPO` | - | 에이전트 다운로드 링크의 GitHub 저장소(기본 `sangjindl9-lab/do`) |

PG·SMTP·AI·Google OAuth 인증정보는 환경변수가 아니라 **관리자 페이지**에서 등록합니다. GitHub 저장소에는 어떤 비밀값도 들어 있지 않습니다.

## 사용자 지정 도메인

Railway 서비스 > Settings > Networking에서 도메인을 추가하고, `PUBLIC_BASE_URL`을 새 주소로 바꾼 뒤 토스 웹훅 주소와 Google OAuth 리디렉션 URI도 함께 바꿉니다.
