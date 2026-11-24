# PC 에이전트 설치설명서 (Google Auto Tester Agent)

## 준비

- 제어 PC: Windows 10/11 64비트 또는 Linux(Ubuntu 22.04+ 권장), 인터넷(서버로 나가는 HTTPS만 필요)
- Android platform-tools(`adb`): <https://developer.android.com/tools/releases/platform-tools> 에서 받아 PATH에 추가하거나, 에이전트 환경 설정에 adb 경로를 지정
- (선택) scrcpy: 기기 화면 미러링용

## 1. 관리자 페이지에서 에이전트 등록

장비관리 > PC 에이전트 > **에이전트 등록** → 이름 입력, 종류 "실기기 폰팜" → 표시되는 **등록 코드**(24시간 유효, 1회용)를 복사합니다.

## 2-A. Windows

1. 관리자 페이지 > PC 에이전트 > 에이전트 다운로드에서 `GoogleAutoTesterAgent-Setup.exe`를 받아 실행합니다.
2. 설치 마법사에서 실행 방식을 고릅니다.
   - **Windows 시작 시 관리 창 자동 실행**(기본): 로그인하면 트레이에서 동작
   - **Windows 서비스로 등록**: 로그인하지 않아도 백그라운드 실행, 장애 시 자동 재시작
3. 관리 창 > 서버 연결·인증 탭에서 서버 주소(`https://...`)와 등록 코드를 입력하고 **에이전트 인증(등록)**.
4. 창을 닫아도 트레이에서 계속 동작합니다. 트레이 메뉴: 창 열기 / 시작 / 중지 / 재시작 / 프로그램 종료.

서비스로 쓰는 경우에도 3번 인증을 먼저 한 뒤 `services.msc`에서 "Google Auto Tester Agent"를 시작합니다.
명령행: `gat-agent.exe enroll --server https://... --code ...`, `gat-agent.exe status`, `gat-agent.exe devices`.
설정·로그 위치: `C:\ProgramData\GoogleAutoTesterAgent\` (`config.json`, `agent.log`).

## 2-B. Linux

```bash
tar -xzf google-auto-tester-agent-linux.tar.gz && cd google-auto-tester-agent
sudo ./install.sh --server https://서버주소 --code 등록코드
systemctl status google-auto-tester-agent        # 상태 확인
journalctl -u google-auto-tester-agent -f        # 로그 조회
```

systemd 서비스로 등록되어 부팅 시 자동 실행되고 장애 시 5초 뒤 재시작합니다. 설정: `/var/lib/google-auto-tester-agent/`.

## 관리 창 메뉴

서버 연결·인증 / 연결 기기(기기 검색, scrcpy 화면 보기) / 검사 진행 현황 / 검사 작업 목록 / 오류 기록 / 환경 설정·업데이트(adb 경로, 동시 검사 기기 수, Appium 서버, 전송 대기 건수, 버전).

## 동작 방식

- 15초마다 기기를 검색해 서버에 상태를 보내고, 작업을 받아 기기별로 실행합니다. 서버가 작업을 만들면 WebSocket으로 즉시 깨웁니다.
- 인터넷이 끊기면 결과·스크린샷을 로컬(`spool/`)에 보관했다가 연결이 복구되면 순서대로 전송합니다.
- adb 서버 오류가 3회 연속되면 adb 서버를 재시작합니다.
- 인증키는 90일(설정 가능) 유효합니다. 관리 창의 **인증키 갱신** 또는 `gat-agent rotate`로 갱신하고, 분실·유출 시 관리자 페이지에서 **인증키 폐기** 후 등록 코드를 재발급합니다.

## 업데이트

새 버전이 있으면 관리 창의 버전 표시에 "새 버전 있음"이 나타납니다. "다운로드 페이지 열기"로 최신 설치 파일을 받아 덮어 설치합니다(설정은 유지). 서버의 기준 버전은 관리자 환경 설정의 `agent.latest_version`입니다.
자동 내려받기·무인 교체 설치는 포함하지 않았습니다(알림 + 수동 설치).

## 설치 파일 빌드

`git tag agent-v1.0.0 && git push origin agent-v1.0.0` → GitHub Actions(`agent-release.yml`)가 Windows(PyInstaller + Inno Setup)·Linux 묶음을 빌드하고, 모의 장비 자체 시험과 서비스 등록 시험을 거쳐 Releases에 올립니다.
