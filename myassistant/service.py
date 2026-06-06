"""Windows service wrapper. Install with scripts/install_service.ps1 (as Administrator).

Once installed:
  net start MyAssistantService
  net stop  MyAssistantService
"""
from __future__ import annotations

import asyncio
import sys

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False


if HAS_PYWIN32:

    class MyAssistantService(win32serviceutil.ServiceFramework):
        _svc_name_ = "MyAssistantService"
        _svc_display_name_ = "MyAssistant Personal Assistant"
        _svc_description_ = "Always-on personal AI assistant reachable via Discord/Telegram/PWA."

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._loop: asyncio.AbstractEventLoop | None = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            if self._loop:
                self._loop.call_soon_threadsafe(self._loop.stop)

        def SvcDoRun(self):
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STARTED,
                                  (self._svc_name_, ""))
            from myassistant.__main__ import _run
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(_run("discord,telegram,http,whatsapp"))
            finally:
                self._loop.close()


def main():
    if not HAS_PYWIN32:
        print("pywin32 not installed; can't run as Windows service.")
        sys.exit(1)
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MyAssistantService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(MyAssistantService)


if __name__ == "__main__":
    main()
