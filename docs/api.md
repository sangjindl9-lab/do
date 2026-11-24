# API 명세서

전체 스키마: [openapi.json](openapi.json) · 실행 중인 서버의 `/api/docs`(Swagger UI)

- 고객·관리자: `Authorization: Bearer <access_token>` (로그인 응답의 access_token, 30분 유효. `/api/auth/refresh`로 갱신)
- PC 에이전트: `X-Agent-Token: <인증키>` (관리자 토큰과 서로 대체 불가)
- 오류 응답: `{"detail": "사유"}`

## 회원·인증

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/api/auth/change-password` | Change Password |
| `POST` | `/api/auth/forgot` | Forgot |
| `GET` | `/api/auth/google/callback` | Google Callback |
| `GET` | `/api/auth/google/start` | Google Start |
| `GET` | `/api/auth/google/status` | Google Status |
| `POST` | `/api/auth/login` | Login |
| `POST` | `/api/auth/logout` | Logout |
| `POST` | `/api/auth/refresh` | Refresh |
| `POST` | `/api/auth/register` | Register |
| `POST` | `/api/auth/resend-verification` | Resend Verification |
| `POST` | `/api/auth/reset` | Reset |
| `POST` | `/api/auth/verify-email` | Verify Email |
| `GET` | `/api/me` | Me |
| `PATCH` | `/api/me` | Update Me |
| `GET` | `/api/me/logins` | My Logins |
| `POST` | `/api/me/withdraw` | 회원 탈퇴: 개인정보를 즉시 익명화한다. 진행 중인 검사가 있으면 먼저 종료해야 한다. |

## 공개

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/public/announcements` | Announcements |
| `GET` | `/api/public/devices` | 지원 기기 안내: 실제 등록된 실기기(모의 장비 제외)만 집계한다. |
| `GET` | `/api/public/faqs` | Faqs |
| `GET` | `/api/public/legal/{key}` | Legal |
| `GET` | `/api/public/products` | Products |
| `GET` | `/api/public/site` | Site |

## 고객

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/apps` | List Apps |
| `POST` | `/api/apps` | Create App |
| `GET` | `/api/apps/{app_id}` | Get App |
| `PUT` | `/api/apps/{app_id}` | Update App |
| `DELETE` | `/api/apps/{app_id}` | Delete App |
| `GET` | `/api/apps/{app_id}/closed-test` | 실제 테스터 수 / 실기기 검사 수량 / 기기 Google 계정 확인 수를 서로 다른 항목으로 분리해 보여준다. |
| `POST` | `/api/apps/{app_id}/icon` | Upload Icon |
| `GET` | `/api/apps/{app_id}/production-notes` | 프로덕션 신청 참고자료(초안). 실제 기록만 요약하며 승인 보장 문구를 포함하지 않는다. |
| `POST` | `/api/apps/{app_id}/testers` | Add Testers |
| `GET` | `/api/apps/{app_id}/testers.csv` | Export Testers |
| `PATCH` | `/api/apps/{app_id}/testers/{tid}` | Patch Tester |
| `DELETE` | `/api/apps/{app_id}/testers/{tid}` | Delete Tester |
| `POST` | `/api/apps/{app_id}/versions` | 앱 버전 등록(+APK 업로드). 형식·크기·해시·중복·패키지명 일치를 검증하고 이상 파일은 격리한다. |
| `GET` | `/api/dashboard` | Dashboard |
| `GET` | `/api/files/{kind}/{obj_id}` | Signed File |
| `GET` | `/api/notifications` | Notifications |
| `POST` | `/api/notifications/read` | Read Notifications |
| `POST` | `/api/orders` | Create Order |
| `GET` | `/api/orders` | List Orders |
| `POST` | `/api/orders/quote` | Quote |
| `GET` | `/api/orders/{order_id}` | Get Order |
| `POST` | `/api/orders/{order_id}/cancel` | Cancel Order |
| `GET` | `/api/plans/{plan_id}` | Plan Detail |
| `GET` | `/api/plans/{plan_id}/crashes` | Plan Crashes |
| `POST` | `/api/plans/{plan_id}/reports` | Make Report |
| `GET` | `/api/plans/{plan_id}/results` | Plan Results |
| `GET` | `/api/plans/{plan_id}/screenshots` | Plan Screenshots |
| `GET` | `/api/reports` | List Reports |
| `GET` | `/api/reports/{report_id}/download` | Download Report |
| `GET` | `/api/scenarios` | List Scenarios |
| `POST` | `/api/scenarios` | Create Scenario |
| `PUT` | `/api/scenarios/{sid}` | 수정 시 새 버전을 만든다(버전 관리). 이전 버전은 보존된다. |
| `DELETE` | `/api/scenarios/{sid}` | Delete Scenario |
| `GET` | `/api/scenarios/{sid}/versions` | Scenario Versions |
| `GET` | `/api/tickets` | List Tickets |
| `POST` | `/api/tickets` | Create Ticket |
| `GET` | `/api/tickets/{tid}` | Get Ticket |
| `POST` | `/api/tickets/{tid}/messages` | Add Message |

## 결제

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/payments` | My Payments |
| `GET` | `/api/payments/config` | Config |
| `POST` | `/api/payments/confirm` | Confirm |
| `POST` | `/api/payments/fail` | 결제창에서 실패/취소된 경우의 기록. |
| `POST` | `/api/payments/mock/issue` | 모의 결제 환경 전용: 모의 결제 키 발급(결제창 대체). 운영 모드에서는 동작하지 않는다. |
| `POST` | `/api/payments/prepare` | 결제 요청 준비. 금액은 항상 서버의 주문 금액을 사용한다. |
| `POST` | `/api/payments/webhook/mock` | 모의 PG 웹훅. HMAC 서명 검증 + 이벤트 ID 중복 차단을 실제와 동일하게 수행한다. |
| `POST` | `/api/payments/webhook/toss` | Webhook Toss |

## PC 에이전트 (X-Agent-Token)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/api/agent/commands/{cmd_id}/result` | Command Result |
| `POST` | `/api/agent/enroll` | 최초 등록: 관리자가 발급한 1회용 등록 코드를 인증키로 교환한다. |
| `GET` | `/api/agent/files/{file_id}` | APK 다운로드. 이 에이전트에 배정된 작업/명령이 참조하는 파일만 허용한다. |
| `POST` | `/api/agent/heartbeat` | Heartbeat |
| `POST` | `/api/agent/jobs/claim` | 작업 수신. 행 잠금(SKIP LOCKED) + 임대 시간 + 기기당 1작업 유일 인덱스로 중복 실행을 방지한다. |
| `POST` | `/api/agent/jobs/{job_id}/fail` | 검사를 수행하지 못한 경우(설치 불가, ADB 오류 등). 재시도 가능하면 지수 백오프로 다시 대기열에 넣는다. |
| `POST` | `/api/agent/jobs/{job_id}/progress` | Progress |
| `POST` | `/api/agent/jobs/{job_id}/result` | Result |
| `POST` | `/api/agent/jobs/{job_id}/screenshot` | Job Screenshot |
| `POST` | `/api/agent/token/rotate` | Rotate |

## 관리자

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/admin/announcements` |  List |
| `POST` | `/api/admin/announcements` |  Create |
| `PUT` | `/api/admin/announcements/{oid}` |  Update |
| `DELETE` | `/api/admin/announcements/{oid}` |  Delete |
| `GET` | `/api/admin/apps` | Apps |
| `GET` | `/api/admin/audit-logs` | Audit Logs |
| `GET` | `/api/admin/backups` | Backups |
| `POST` | `/api/admin/backups` | Backup Now |
| `GET` | `/api/admin/backups/{bid}/download` | Backup Download |
| `POST` | `/api/admin/backups/{bid}/restore` | Backup Restore |
| `GET` | `/api/admin/coupons` |  List |
| `POST` | `/api/admin/coupons` |  Create |
| `PUT` | `/api/admin/coupons/{oid}` |  Update |
| `DELETE` | `/api/admin/coupons/{oid}` |  Delete |
| `GET` | `/api/admin/customers` | Customers |
| `GET` | `/api/admin/customers/{cid}` | Customer Detail |
| `GET` | `/api/admin/dashboard` | Dashboard |
| `GET` | `/api/admin/device-groups` |  List |
| `POST` | `/api/admin/device-groups` |  Create |
| `PUT` | `/api/admin/device-groups/{oid}` |  Update |
| `DELETE` | `/api/admin/device-groups/{oid}` |  Delete |
| `GET` | `/api/admin/emails` | Emails |
| `GET` | `/api/admin/faqs` |  List |
| `POST` | `/api/admin/faqs` |  Create |
| `PUT` | `/api/admin/faqs/{oid}` |  Update |
| `DELETE` | `/api/admin/faqs/{oid}` |  Delete |
| `GET` | `/api/admin/files/quarantine` | Quarantine |
| `DELETE` | `/api/admin/files/quarantine/{fid}` | Delete Quarantined |
| `GET` | `/api/admin/legal` | Legal List |
| `PUT` | `/api/admin/legal/{key}` | Legal Put |
| `GET` | `/api/admin/notification-templates` |  List |
| `POST` | `/api/admin/notification-templates` |  Create |
| `PUT` | `/api/admin/notification-templates/{oid}` |  Update |
| `DELETE` | `/api/admin/notification-templates/{oid}` |  Delete |
| `GET` | `/api/admin/orders` | Orders |
| `GET` | `/api/admin/orders/{oid}` | Order Detail |
| `POST` | `/api/admin/orders/{oid}/cancel` | 미결제 주문 취소 또는 진행 중 검사 중단(환불은 결제 관리에서 별도 처리). |
| `GET` | `/api/admin/payment-events` | Payment Events |
| `GET` | `/api/admin/payments` | Payments |
| `GET` | `/api/admin/payments/{pid}` | Payment Detail |
| `POST` | `/api/admin/payments/{pid}/refund` | Refund |
| `GET` | `/api/admin/pg` | Pg Get |
| `PUT` | `/api/admin/pg` | Pg Put |
| `POST` | `/api/admin/pg/test` | 연동 시험: 존재하지 않는 결제를 조회해 인증 성공 여부(401 vs 404)를 확인한다. 금전 거래는 발생하지 않는다. |
| `GET` | `/api/admin/products` |  List |
| `POST` | `/api/admin/products` |  Create |
| `PUT` | `/api/admin/products/{oid}` |  Update |
| `DELETE` | `/api/admin/products/{oid}` |  Delete |
| `GET` | `/api/admin/refunds` | Refunds |
| `GET` | `/api/admin/revenue` | 매출 집계. 모의 결제는 실매출과 완전히 분리해 별도 항목으로만 표시한다. |
| `GET` | `/api/admin/roles` | Roles |
| `PUT` | `/api/admin/roles/{code}` | Set Role Permissions |
| `GET` | `/api/admin/settings` | Settings Get |
| `PUT` | `/api/admin/settings` | 비밀값은 빈 문자열이면 기존 값을 유지한다. PG 키는 결제 관리 권한 메뉴에서만 변경한다. |
| `POST` | `/api/admin/settings/test-ai` | Test Ai |
| `POST` | `/api/admin/settings/test-email` | Test Email |
| `GET` | `/api/admin/status` | Status |
| `GET` | `/api/admin/system-logs` | System Logs |
| `GET` | `/api/admin/tickets` | Tickets |
| `GET` | `/api/admin/tickets/{tid}` | Ticket |
| `POST` | `/api/admin/tickets/{tid}/reply` | Reply |
| `GET` | `/api/admin/users` | Users |
| `POST` | `/api/admin/users` | Create Staff |
| `PATCH` | `/api/admin/users/{uid}` | Patch User |

## 관리자: 장비·검사

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/admin/agent-downloads` | Agent Downloads |
| `GET` | `/api/admin/agents` | Agents |
| `POST` | `/api/admin/agents` | 에이전트 등록: 고유 ID와 1회용 등록 코드(24시간 유효)를 발급한다. 코드는 이 응답에서만 보인다. |
| `POST` | `/api/admin/agents/{aid}/enroll-code` | Reissue Code |
| `POST` | `/api/admin/agents/{aid}/revoke` | 인증키 전체 폐기 + 에이전트 사용 중지. |
| `POST` | `/api/admin/agents/{aid}/tokens/{tid}/revoke` | Revoke Token |
| `POST` | `/api/admin/commands` | Send Commands |
| `GET` | `/api/admin/commands` | Commands |
| `GET` | `/api/admin/crashes` | Crashes |
| `POST` | `/api/admin/crashes/{cid}/analyze` | AI 추정 분석 재실행. AI 미설정 시 규칙 기반 분석만 갱신한다. |
| `GET` | `/api/admin/devices` | Devices |
| `GET` | `/api/admin/devices/{did}` | Device Detail |
| `PATCH` | `/api/admin/devices/{did}` | Patch Device |
| `DELETE` | `/api/admin/devices/{did}` | Delete Device |
| `GET` | `/api/admin/incidents` | 장비 장애 관리: 문제 상태 기기 + 오프라인 에이전트 + 관련 시스템 로그. |
| `GET` | `/api/admin/jobs` | Jobs |
| `POST` | `/api/admin/jobs/{jid}/{action}` | Job Action |
| `GET` | `/api/admin/live` | 실시간 검사 현황. |
| `GET` | `/api/admin/plans` | Plans |
| `PATCH` | `/api/admin/plans/{pid}` | Patch Plan |
| `GET` | `/api/admin/plans/{pid}` | Plan Detail |
| `POST` | `/api/admin/plans/{pid}/{action}` | Plan Action |
| `GET` | `/api/admin/reports` | Reports |
| `POST` | `/api/admin/reports` | Make Report |
| `GET` | `/api/admin/results` | Results |
| `GET` | `/api/admin/scenarios` | Scenarios |
| `POST` | `/api/admin/scenarios` | Create Scenario |
| `PUT` | `/api/admin/scenarios/{sid}` | Update Scenario |
| `DELETE` | `/api/admin/scenarios/{sid}` | Delete Scenario |
| `GET` | `/api/admin/screenshots` | Screenshots |
| `POST` | `/api/admin/transfer-files` | 기기로 전송할 파일 업로드(50MB 이하). |

## 기타

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/health` | Railway 헬스체크: DB 연결과 저장소 쓰기 가능 여부를 확인한다. |
