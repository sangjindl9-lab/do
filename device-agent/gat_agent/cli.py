"""명령행 진입점: gat-agent enroll | run | status | devices | rotate | selftest | gui"""
import argparse
import json
import logging
import logging.handlers
import os
import signal
import sys

from . import __version__
from .config import load


def _logging(cfg, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(cfg.log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")]
    if sys.stderr and sys.stderr.isatty() or verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def selftest() -> int:
    """모의 장비로 검사 엔진을 실제 실행해 본다(서버 불필요). 빌드된 실행 파일의 동작 검증용."""
    from gat_engine import run_job
    from gat_engine.providers import MockProvider
    provider = MockProvider(2)
    provider.prepare("com.example.selftest", "1.0")
    payload = {"package": "com.example.selftest", "version_name": "1.0", "apk": {"file_id": 0},
               "checks": ["install", "launch", "cold_start", "display", "orientation", "background", "restart", "crash", "anr"]}
    result = run_job(provider, provider.serials[0], payload, apk_path="selftest.apk", sleep=lambda s: None, settle=0)
    print(json.dumps({"version": __version__, "provider": "mock", "status": result["status"], "summary": result["summary"]}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gat-agent", description="Google Auto Tester Agent")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--home", help="설정·로그 폴더")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("enroll", help="서버에 최초 등록(관리자 페이지에서 발급한 등록 코드 사용)")
    p.add_argument("--server", required=True)
    p.add_argument("--code", required=True)
    p = sub.add_parser("run", help="에이전트 실행(백그라운드 서비스용)")
    p.add_argument("--provider", choices=["adb", "mock"])
    p.add_argument("--mock-devices", type=int)
    p = sub.add_parser("set", help="환경 설정 변경")
    p.add_argument("--adb-path")
    p.add_argument("--max-parallel", type=int)
    p.add_argument("--provider", choices=["adb", "mock"])
    p.add_argument("--appium-url")
    sub.add_parser("status", help="설정·연결 상태 확인")
    sub.add_parser("devices", help="연결 기기 검색")
    sub.add_parser("rotate", help="인증키 갱신")
    sub.add_parser("selftest", help="모의 장비 자체 시험")
    sub.add_parser("gui", help="관리 창 실행")
    args = parser.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    cfg = load(args.home)
    _logging(cfg, args.verbose)
    if args.cmd in (None, "gui"):
        from .gui import run_gui
        return run_gui(cfg)
    from .api import ApiError, NetworkError
    from .core import Agent, enroll, make_provider, rotate_token
    try:
        if args.cmd == "enroll":
            data = enroll(cfg, args.server, args.code)
            print(f"등록 완료: {data['name']} ({data['agent_id']}), 인증키 만료 {data['expires_at']}")
        elif args.cmd == "set":
            for key in ("adb_path", "max_parallel", "provider", "appium_url"):
                if getattr(args, key) is not None:
                    setattr(cfg, key, getattr(args, key))
            cfg.save()
            print("저장되었습니다.")
        elif args.cmd == "status":
            print(json.dumps({"version": __version__, "home": cfg.home, "server_url": cfg.server_url, "agent_id": cfg.agent_id,
                              "enrolled": bool(cfg.token), "token_expires_at": cfg.token_expires_at, "provider": cfg.provider,
                              "spooled": len(os.listdir(cfg.spool_dir))}, ensure_ascii=False, indent=2))
        elif args.cmd == "devices":
            provider = make_provider(cfg)
            for serial, state in provider.list_serials().items():
                info = provider.describe(serial, []) if state == "device" else None
                print(serial, state, f"{info.manufacturer} {info.model} Android {info.android_version}" if info else "")
        elif args.cmd == "rotate":
            rotate_token(cfg)
            print(f"인증키를 갱신했습니다. 만료 {cfg.token_expires_at}")
        elif args.cmd == "run":
            if not cfg.token:
                print("먼저 'gat-agent enroll'로 등록해 주세요.", file=sys.stderr)
                return 2
            if args.provider:
                cfg.provider = args.provider
            if args.mock_devices:
                cfg.mock_devices = args.mock_devices
            agent = Agent(cfg)
            signal.signal(signal.SIGTERM, lambda *_: agent.stop())
            try:
                agent.run_forever()
            except KeyboardInterrupt:
                agent.stop()
    except (ApiError, NetworkError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
