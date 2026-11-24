"""Windows 서비스(pywin32). 설치: GoogleAutoTesterAgentService.exe install / start / stop / remove"""
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

from .cli import _logging
from .config import load
from .core import Agent


class AgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "GoogleAutoTesterAgent"
    _svc_display_name_ = "Google Auto Tester Agent"
    _svc_description_ = "폰팜 기기를 검색하고 서버에서 받은 검사 작업을 실행합니다."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.agent = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.agent:
            self.agent.stop()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        cfg = load()
        _logging(cfg, False)
        if not cfg.token:
            servicemanager.LogErrorMsg("에이전트가 등록되지 않았습니다. 관리 창에서 먼저 인증해 주세요.")
            return
        self.agent = Agent(cfg)
        self.agent.run_forever()


def main():
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(AgentService)


if __name__ == "__main__":
    main()
