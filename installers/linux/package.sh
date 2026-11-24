#!/usr/bin/env bash
# Linux용 에이전트 배포 묶음(tar.gz) 생성
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/dist/stage/google-auto-tester-agent"
rm -rf "$ROOT/dist/stage" && mkdir -p "$OUT"
cp -r "$ROOT/device-agent/gat_agent" "$ROOT/android-engine/gat_engine" "$OUT/"
cp "$ROOT/installers/linux/install.sh" "$ROOT/installers/linux/google-auto-tester-agent.service" "$OUT/"
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
rm -f "$OUT/gat_agent/service_win.py"
tar -czf "$ROOT/dist/google-auto-tester-agent-linux.tar.gz" -C "$ROOT/dist/stage" google-auto-tester-agent
echo "created dist/google-auto-tester-agent-linux.tar.gz"
