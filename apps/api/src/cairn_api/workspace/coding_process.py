"""Finite, non-interactive commands; kill the entire command tree on every exit."""

import codecs
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from cairn_api.errors import ApiProblem


def problem(code: str, message: str) -> ApiProblem:
    return ApiProblem(status_code=409, code=code, message=message)


def command_environment(git: Path) -> dict[str, str]:
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'HOME',
               'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'LANG', 'LC_ALL'}
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    environment['PATH'] = str(git.parent) + os.pathsep + environment.get('PATH', '')
    environment.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1', 'GIT_TERMINAL_PROMPT': '0'})
    return environment


def windows_job(pid: int, *, suspended: bool = True) -> Callable[[], None]:
    if sys.platform != 'win32':
        raise RuntimeError('Windows process containment requires Windows')
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                    ('Flags', wintypes.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                    ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcesses', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('Priority', wintypes.DWORD), ('Scheduling', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]

    class Limits(ctypes.Structure):
        _fields_ = [('Basic', BasicLimits), ('Io', IoCounters), ('ProcessMemory', ctypes.c_size_t),
                    ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    resume = ctypes.WinDLL('ntdll').NtResumeProcess
    resume.argtypes = [wintypes.HANDLE]
    resume.restype = wintypes.LONG
    job = kernel.CreateJobObjectW(None, None)
    handle = kernel.OpenProcess(0x0001 | 0x0100 | 0x0800, False, pid)
    limits = Limits()
    limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    try:
        if (not job or not handle or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(job, handle)
                or (suspended and resume(handle) != 0)):
            raise OSError(ctypes.get_last_error(), 'Cannot contain command process tree')
    except BaseException:
        if job:
            kernel.CloseHandle(job)
        raise
    finally:
        if handle:
            kernel.CloseHandle(handle)
    def close() -> None:
        kernel.CloseHandle(job)
    return close


def run_command(
    argv: list[str], root: Path, git: Path, timeout: int,
    check: Callable[[], None], output: Callable[[str], None],
) -> tuple[int, str]:
    environment = command_environment(git)
    executable = shutil.which(argv[0], path=environment['PATH'])
    if executable and Path(executable).suffix.lower() in {'.cmd', '.bat'}:
        raise problem('coding_command_shell_required', '批处理命令需明确使用 cmd.exe /c 调用并重新确认完整参数')
    check()
    process = subprocess.Popen(
        argv, cwd=root, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=os.name != 'nt',
        creationflags=(0x08000000 | 0x00000004) if os.name == 'nt' else 0,
    )
    close_job: Callable[[], None] | None = None
    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
    stop = threading.Event()
    assert process.stdout is not None
    stream = process.stdout

    def read() -> None:
        try:
            while not stop.is_set():
                chunk = os.read(stream.fileno(), 4096)
                while not stop.is_set():
                    try:
                        chunks.put(chunk or None, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    break
        except OSError:
            if not stop.is_set():
                chunks.put(None)

    reader = threading.Thread(target=read, daemon=True)
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    collected: list[str] = []
    total = 0
    started = time.monotonic()
    try:
        if os.name == 'nt':
            close_job = windows_job(process.pid)
        reader.start()
        while True:
            check()
            if time.monotonic() - started > timeout:
                raise problem('coding_command_timeout', f'命令超过 {timeout} 秒，已停止进程树')
            try:
                chunk = chunks.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None and chunks.empty() and not reader.is_alive():
                    break
                continue
            if chunk is None:
                break
            total += len(chunk)
            if total > 65536:
                raise problem('coding_output_limit', '命令输出超过 64 KiB，已停止；请缩小命令输出范围')
            text = decoder.decode(chunk)
            collected.append(text)
            output(text)
        final = decoder.decode(b'', final=True)
        if final:
            collected.append(final)
            output(final)
        while process.poll() is None:
            check()
            if time.monotonic() - started > timeout:
                raise problem('coding_command_timeout', f'命令超过 {timeout} 秒，已停止进程树')
            time.sleep(0.05)
        return process.returncode, ''.join(collected)
    finally:
        stop.set()
        if close_job is not None:
            close_job()
        elif os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if reader.is_alive():
            reader.join(timeout=2)
        stream.close()
