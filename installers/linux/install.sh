#!/usr/bin/env bash
# Google Auto Tester Agent - Linux 설치 스크립트 (systemd)
# 사용: sudo ./install.sh --server https://서버주소 --code 등록코드
set -euo pipefail
SERVER="" CODE=""
while [ $# -gt 0 ]; do case "$1" in --server) SERVER="$2"; shift 2;; --code) CODE="$2"; shift 2;; *) echo "알 수 없는 옵션: $1"; exit 2;; esac; done
[ "$(id -u)" -eq 0 ] || { echo "root 권한(sudo)으로 실행해 주세요."; exit 1; }
command -v python3 >/dev/null || { echo "python3(3.10 이상)가 필요합니다."; exit 1; }
command -v adb >/dev/null || echo "경고: adb가 PATH에 없습니다. 'apt install android-tools-adb' 등으로 설치해 주세요."
SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/google-auto-tester-agent
HOME_DIR=/var/lib/google-auto-tester-agent
mkdir -p "$APP" "$HOME_DIR"
cp -r "$SRC/gat_agent" "$SRC/gat_engine" "$APP/"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet --upgrade pip httpx websockets
cat > /usr/local/bin/gat-agent <<WRAP
#!/bin/sh
export GAT_AGENT_HOME=$HOME_DIR PYTHONPATH=$APP
exec $APP/venv/bin/python -m gat_agent "\$@"
WRAP
chmod 755 /usr/local/bin/gat-agent
chmod 700 "$HOME_DIR"
if [ -n "$SERVER" ] && [ -n "$CODE" ]; then gat-agent enroll --server "$SERVER" --code "$CODE"; fi
install -m 644 "$SRC/google-auto-tester-agent.service" /etc/systemd/system/google-auto-tester-agent.service
systemctl daemon-reload
systemctl enable google-auto-tester-agent >/dev/null
if [ -f "$HOME_DIR/config.json" ]; then systemctl restart google-auto-tester-agent; echo "설치 및 시작 완료."; else echo "설치 완료. 'sudo gat-agent enroll --server ... --code ...' 후 'sudo systemctl start google-auto-tester-agent' 를 실행해 주세요."; fi
echo "상태: systemctl status google-auto-tester-agent   로그: journalctl -u google-auto-tester-agent -f"
