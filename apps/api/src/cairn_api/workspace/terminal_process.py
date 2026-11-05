import base64
import codecs
import importlib
import os
import select
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import psutil

from cairn_api.workspace.coding_process import command_environment, windows_job


class WindowsPty(Protocol):
    pid: int
    def spawn(self, appname: str, *, cmdline: str, cwd: str, env: str) -> bool: ...
    def read(self, *, blocking: bool) -> str: ...
    def write(self, text: str) -> int: ...
    def set_size(self, cols: int, rows: int) -> None: ...
    def isalive(self) -> bool: ...
    def get_exitstatus(self) -> int | None: ...


class PosixPty(Protocol):
    pid: int
    fd: int
    exitstatus: int | None
    signalstatus: int | None
    def read(self, size: int) -> bytes: ...
    def setwinsize(self, rows: int, cols: int) -> None: ...
    def isalive(self) -> bool: ...
    def close(self, force: bool) -> None: ...


class TerminalProcess:
    windows_error: type[Exception]

    def __init__(self, root: Path, git: Path, cols: int, rows: int):
        self.windows: WindowsPty | None = None
        self.posix: PosixPty | None = None
        self.close_job: Callable[[], None] | None = None
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        environment = command_environment(git)
        environment.update({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'HISTFILE': os.devnull})
        if os.name == 'nt':
            module = importlib.import_module('winpty')
            self.windows_error = cast(type[Exception], module.WinptyError)
            factory = cast(Callable[..., WindowsPty], module.PTY)
            self.windows = factory(cols, rows, backend=0)
            shell = Path(os.environ['SYSTEMROOT']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            self.shell = 'PowerShell'
            script = Path(__file__).with_name('terminal.ps1').read_text(encoding='utf-8')
            script = 'try {\n' + script + '\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }'
            arguments = ['-NoLogo', '-NoProfile', '-NoExit', '-EncodedCommand',
                         base64.b64encode(script.encode('utf-16le')).decode('ascii')]
            if not self.windows.spawn(str(shell), cmdline=' ' + subprocess.list2cmdline(arguments),
                                      cwd=str(root), env='\0'.join(f'{key}={value}' for key, value in environment.items()) + '\0'):
                raise OSError('ConPTY could not start PowerShell')
            self.pid = self.windows.pid
            try:
                self.close_job = windows_job(self.pid, suspended=False)
            except BaseException:
                psutil.Process(self.pid).kill()
                self.windows = None
                raise
        else:
            spawn = cast(Callable[..., PosixPty], importlib.import_module('ptyprocess').PtyProcess.spawn)
            self.posix = spawn(['/bin/bash', '--noprofile', '--rcfile', str(Path(__file__).with_name('terminal.bash')), '-i'], cwd=str(root),
                               env=environment, dimensions=(rows, cols))
            self.pid = self.posix.pid
            self.shell = 'Bash'
            os.set_blocking(self.posix.fd, False)

    def read(self) -> str:
        if self.windows:
            try:
                return self.windows.read(blocking=False)
            except self.windows_error:
                if self.windows.isalive():
                    raise
                return ''
        assert self.posix
        if not select.select([self.posix.fd], [], [], 0)[0]:
            return ''
        try:
            return self.decoder.decode(self.posix.read(8192))
        except EOFError:
            return self.decoder.decode(b'', final=True)

    def write(self, text: str, stopping: threading.Event) -> None:
        if self.windows:
            self.windows.write(text)
        else:
            assert self.posix
            remaining = text.encode('utf-8')
            while remaining:
                if stopping.is_set():
                    raise OSError('Terminal is closing')
                if not select.select([], [self.posix.fd], [], .1)[1]:
                    continue
                try:
                    written = os.write(self.posix.fd, remaining)
                    remaining = remaining[written:]
                except BlockingIOError:
                    continue

    def resize(self, cols: int, rows: int) -> None:
        if self.windows:
            self.windows.set_size(cols, rows)
        else:
            assert self.posix
            self.posix.setwinsize(rows, cols)

    def alive(self) -> bool:
        if self.windows:
            return self.windows.isalive()
        assert self.posix
        return self.posix.isalive()

    def exit_code(self) -> int | None:
        if self.windows:
            return self.windows.get_exitstatus()
        assert self.posix
        return self.posix.exitstatus if self.posix.exitstatus is not None else -self.posix.signalstatus if self.posix.signalstatus else None

    def close(self) -> None:
        if self.close_job:
            self.close_job()
            self.close_job = None
            self.windows = None
        if self.posix:
            descendants: list[psutil.Process] = []
            for process in psutil.process_iter():
                try:
                    if os.getsid(process.pid) == self.pid:
                        if process.pid != self.pid:
                            descendants.append(process)
                        process.kill()
                except (ProcessLookupError, psutil.NoSuchProcess):
                    continue
            psutil.wait_procs(descendants, timeout=2)
            self.posix.close(force=True)
            self.posix = None
