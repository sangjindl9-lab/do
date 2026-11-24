# 테스트 실행 결과

실행일: 2026-11-24. 아래 결과는 모두 실제로 실행한 것입니다. 실물 장비·실제 PG가 필요한 항목은 실행하지 않았고 "대기"로 분류했습니다.

## 1. 통합 테스트 (pytest) — 45건 통과

환경: PostgreSQL 16, Alembic 마이그레이션으로 만든 스키마, **실제 에이전트 코드(gat_agent) + 모의 장비(MockProvider)** 를 테스트 서버에 연결.
같은 테스트가 GitHub Actions(CI)에서도 푸시마다 실행되어 통과했습니다.

| 영역 | 확인한 내용 |
| --- | --- |
| 고객 기능 | 회원가입(중복·약한 비밀번호·약관 미동의 거부), 로그인, 로그아웃, 갱신 토큰 회전, 이메일 인증, 비밀번호 재설정(기존 세션 폐기), 5회 실패 시 계정 잠금, 앱 등록·패키지명 검증, APK 업로드(해시·중복·형식 위반 격리·패키지명 불일치 격리·버전 이력), 상품 조회, 쿠폰, 주문 생성(멱등 키)·조회·취소, 문의·알림, 회원 탈퇴 |
| 결제 | PG 미등록 시 결제 비활성, PG 설정 검증·비밀키 비노출, 모의 결제 승인 → 검사 계획 생성, **금액 위변조 차단**, **중복 결제 차단**, 결제 실패 후 재결제, 웹훅 서명 검증·**중복 수신 무시**, 부분/전체 환불(멱등)·환불 시 검사 중단, 모의 매출 분리, 토스 API 요청 형식(모의 전송 계층) |
| 장비 | 에이전트 등록 코드 1회용·인증키 갱신·폐기, 관리자 토큰 ↔ 에이전트 토큰 상호 불가, 모의 기기 등록, 과열·저장공간 부족·오프라인 상태 갱신, 연결 끊김 감지·관리자 알림·재연결, 기기 부족 시 대기 → 확보 후 자동 배정, **실제 주문에 모의 기기 미배정**, 작업 수신·실행·결과/스크린샷/성능/크래시 저장, **미수행 검사를 성공으로 기록 불가**, 원격 명령 허용 목록, APK 다운로드 권한 |
| 자동화 | 반복 일정·특정 시간, 회차 중복 생성 없음, **동시 8건 수신 요청에도 작업·기기 중복 없음**, 실패 재시도(지수 백오프)·최대 횟수 후 '수행 불가' 기록, 타임아웃 회수, **서버 재시작 후 일정·작업 보존**, 오프라인 중 결과 로컬 보관 → 동기화, 오프라인 기기 대체 배정, 일시정지·재개·취소(에이전트 취소 통지, 고객 앱 정리 명령), 기간 종료 → 최종 보고서 자동 생성·알림·다운로드(PDF 8종, Excel 수치 대조) |
| 보안 | 헬스체크·보안 헤더, 관리자 메뉴 39개 전부 비로그인 401 / 고객 403 / 관리자 200, 역할별 권한, **고객 간 데이터 격리 18개 경로**, 시나리오 검증·버전 관리, 실제 테스터와 기기 검사 분리, 관리자 CRUD·감사 로그·비밀값 암호화 저장, XSS·SQL 주입 입력 무해화, 백업 → 변경 → 복구 왕복 |

<details><summary>통과한 테스트 목록</summary>

```
test_customer.py::test_register_login_logout_refresh
test_customer.py::test_email_verification_and_password_reset
test_customer.py::test_email_queue_marks_not_sent_without_smtp
test_customer.py::test_account_lock_after_failed_logins
test_customer.py::test_app_registration_and_validation
test_customer.py::test_apk_upload_hash_duplicate_and_quarantine
test_customer.py::test_products_orders_and_coupon
test_customer.py::test_support_ticket_and_notifications
test_customer.py::test_withdraw_anonymizes_account
test_devices.py::test_agent_enroll_and_token_lifecycle
test_devices.py::test_admin_token_cannot_be_used_as_agent_and_vice_versa
test_devices.py::test_mock_devices_register_and_update_status
test_devices.py::test_disconnect_detection_and_reconnect
test_devices.py::test_auto_allocation_wait_then_assign
test_devices.py::test_real_orders_never_get_mock_devices
test_devices.py::test_job_claim_run_and_store_results
test_devices.py::test_result_cannot_be_recorded_as_pass_without_execution
test_devices.py::test_remote_commands_are_allowlisted
test_devices.py::test_apk_download_restricted_to_assigned_agent
test_payment.py::test_payment_disabled_without_pg_credentials
test_payment.py::test_pg_settings_validation
test_payment.py::test_mock_payment_success_creates_plan
test_payment.py::test_amount_tampering_is_blocked
test_payment.py::test_payment_failure_keeps_order_payable
test_payment.py::test_webhook_signature_and_duplicate
test_payment.py::test_partial_and_full_refund
test_payment.py::test_revenue_separates_mock_from_real
test_payment.py::test_toss_provider_request_shape
test_scheduler.py::test_schedule_repeats_and_never_duplicates
test_scheduler.py::test_concurrent_claims_never_double_run
test_scheduler.py::test_failed_job_retries_with_backoff_then_records_error
test_scheduler.py::test_timeout_reclaims_lease_and_server_restart_recovers
test_scheduler.py::test_agent_spools_results_while_offline_and_syncs
test_scheduler.py::test_offline_device_is_replaced
test_scheduler.py::test_pause_resume_cancel
test_scheduler.py::test_full_cycle_completion_and_reports
test_security.py::test_health_and_public_pages
test_security.py::test_every_admin_menu_requires_admin
test_security.py::test_role_based_menu_permissions
test_security.py::test_tenant_isolation
test_security.py::test_scenario_versioning_and_validation
test_security.py::test_closed_test_separates_human_testers_from_device_runs
test_security.py::test_admin_crud_audit_and_settings_masking
test_security.py::test_xss_payload_is_stored_as_data_and_sqli_is_inert
test_security.py::test_backup_and_restore_roundtrip
```
</details>

## 2. 브라우저 E2E (Playwright + Chrome, 로컬 서버) — 문제 0건

`scripts/e2e_browser.py`. 실제 화면 조작으로 회원가입 → 앱 등록 → APK 업로드 → 상품 선택 → 주문 → 모의 결제까지 진행하고,
**별도 프로세스로 띄운 에이전트(CLI, 모의 기기 20대)** 가 HTTPS API + WebSocket으로 서버에 붙어 서버 스케줄러가 만든 작업 20건을 수행하는 것을 확인했습니다.

- 열어 본 화면 86개: 공개 14, 고객 11(+주문 상세 탭 6), 관리자 35, 모바일 폭(390px) 26
- 브라우저 콘솔 오류·5xx 응답 0건, 모바일 가로 넘침 0건, 영어 전환 확인
- 관리자 화면에서 기기 전체 선택 → 스크린샷 명령 → 결과 이미지 수신 확인
- 고객 계정으로 관리자 화면 접근 시 차단 확인

이 과정에서 찾아 고친 결함: 새로고침 중 갱신 토큰 경합으로 로그아웃되던 문제, 글꼴 CSP 차단, 전역 요청 한도 과소, 에이전트의 로컬 보관분 동기화 경합(에이전트 정지), 계정 화면 모바일 넘침.

## 3. 배포 검증 (Railway)

- 빌드·배포 성공, 컨테이너 시작 시 마이그레이션 적용, Railway 헬스체크(`/api/health`) 통과, 스케줄러 20초 주기 실행 로그 확인
- 공개 주소 접속 검증(GitHub Actions `Verify Deploy`, `scripts/smoke_remote.py`): 헬스체크, 볼륨 쓰기 가능, 고객 웹사이트·요금제·로그인·관리자 페이지 200, 상품 API(DB 초기 데이터), 고지 문구, 결제 비활성(PG 미등록), 비로그인 API 401, 에이전트 API 401, 잘못된 관리자 비밀번호 401

배포 서버에서는 **관리자 로그인 이후 화면과 주문·결제·검사 흐름을 실행하지 않았습니다.** 이 부분은 같은 코드로 로컬에서만 검증했습니다.

## 4. PC 에이전트 빌드 (GitHub Actions `Agent Release`) — 성공

- Windows: PyInstaller 빌드 → `gat-agent.exe selftest`(모의 장비로 검사 엔진 실행) → Windows 서비스 등록·조회·해제 → Inno Setup 설치 파일 생성
- Linux: 배포 묶음 생성 → 풀어서 selftest
- 관리 창(PySide6)은 화면 없는 모드로 띄워 탭 6개 구성 확인

Windows 설치 마법사를 사람이 직접 실행해 보는 것과 실제 PC에서의 트레이 동작은 확인하지 못했습니다.

## 5. 실행하지 않은 것

| 구분 | 항목 |
| --- | --- |
| 실제 장비 검증 대기 | 실기기 ADB 제어 전체(`AdbProvider`: 설치·실행·UI 덤프·회전·성능·Logcat 파싱), 20대 동시 검사, 과열·저장공간 실측, scrcpy 미러링, Appium 드라이버, Linux systemd 서비스 실제 설치 |
| 실제 PG 인증정보 대기 | 토스 결제창 호출, 승인·취소 API 실제 왕복, 실제 웹훅 수신 |
| 외부 연동 대기 | SMTP 실제 발송, Google OAuth 로그인, AI(OpenAI·Claude·Gemini·로컬) 분석 호출 |
