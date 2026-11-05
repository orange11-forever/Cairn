import base64
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psutil
import pytest
from cairn_api.errors import ApiProblem
from cairn_api.workspace import terminal
from cairn_api.workspace.editor import RepositoryEditor
from cairn_api.workspace.local import DesktopWorkspace


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[tuple[DesktopWorkspace, UUID, UUID, Path]]:
    root, data = tmp_path / '代码 repo', tmp_path / 'data'
    root.mkdir()
    data.mkdir()
    git = shutil.which('git')
    assert git
    subprocess.run([git, '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    current = DesktopWorkspace(data, Path(git), None, base64.b64encode, base64.b64decode)
    user, project = uuid4(), uuid4()
    current.bind_local(user, project, str(root))
    yield current, user, project, root
    if current.terminals:
        current.terminals.close()


def until(check: Callable[[], bool], seconds: float = 8) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.03)
    assert check()


def test_terminal_keeps_shell_input_unicode_cwd_resize_and_exit(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, root = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id,
        allow_execution=True,
    ), lambda: None)
    session = service.session(user, project, snapshot.id)
    try:
        session.write("mkdir child\rcd child\r")
        if os.name == 'nt':
            session.write("$answer = Read-Host 'VALUE'\r")
        else:
            session.write("read -p VALUE answer\r")
        until(lambda: 'VALUE' in session.snapshot(0).output)
        session.write('你好\r')
        command = "[IO.File]::WriteAllText((Join-Path $PWD 'result.txt'), $answer)\r" if os.name == 'nt' else "printf '%s' \"$answer\" > result.txt\r"
        session.write(command)
        until(lambda: (root / 'child/result.txt').exists())
        assert (root / 'child/result.txt').read_text(encoding='utf-8') == '你好'
        session.resize(100, 30)
        if os.name != 'nt':
            session.write('stty size > size.txt\r')
            until(lambda: (root / 'child/size.txt').exists())
            assert (root / 'child/size.txt').read_text().strip() == '30 100'
        session.write('exit 7\r')
        until(lambda: session.snapshot(0).status != 'running')
        assert session.snapshot(0).exit_code == 7
    finally:
        service.close()


def test_ctrl_c_interrupts_foreground_without_closing_shell(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, root = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id,
        allow_execution=True,
    ), lambda: None)
    session = service.session(user, project, snapshot.id)
    session.write("'ready' | Set-Content ready.txt; Start-Sleep 120\r" if os.name == 'nt' else 'echo ready > ready.txt; sleep 120\r')
    until(lambda: (root / 'ready.txt').exists())
    offset = session.snapshot(0).next_offset
    session.write('\x03')
    if os.name == 'nt':
        until(lambda: '❯' in session.snapshot(offset).output)
    session.write("'alive' | Set-Content alive.txt\r" if os.name == 'nt' else 'echo alive > alive.txt\r')
    until(lambda: (root / 'alive.txt').exists())
    assert session.snapshot(0).status == 'running'


def test_close_kills_child_tree_without_stopping_another_terminal(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, root = workspace
    script = 'import os, subprocess, sys, time\nfrom pathlib import Path\nchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])\nPath("children.txt").write_text(str(os.getpid()) + "," + str(child.pid))\ntime.sleep(120)\n'
    (root / 'tree.py').write_text(script)
    service = terminal.TerminalManager(current)
    current.terminals = service
    payload = terminal.TerminalStart(workspace_id=RepositoryEditor(current, user, project).tree().workspace_id, allow_execution=True)
    first = service.start(user, project, payload, lambda: None)
    other_project = uuid4()
    current.bind_local(user, other_project, str(root))
    second = service.start(user, other_project, payload, lambda: None)
    session = service.session(user, project, first.id)
    session.write(f"& '{sys.executable}' tree.py\r" if os.name == 'nt' else f'"{sys.executable}" tree.py\r')
    until(lambda: (root / 'children.txt').exists())
    children = [psutil.Process(int(value)) for value in (root / 'children.txt').read_text().split(',')]
    session.stop()
    until(lambda: all(not child.is_running() or child.status() == psutil.STATUS_ZOMBIE for child in children))
    assert session.snapshot(0).status == 'stopped'
    assert service.session(user, other_project, second.id).snapshot(0).status == 'running'


def test_session_ownership_revocation_and_binding_guard(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, _ = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    revoked = False

    def authorize() -> None:
        if revoked:
            raise ApiProblem(status_code=403, code='forbidden', message='Project access revoked')

    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id,
        allow_execution=True,
    ), authorize)
    with pytest.raises(ApiProblem, match='终端'):
        service.session(uuid4(), project, snapshot.id)
    with pytest.raises(ApiProblem):
        service.require_idle(user, project)
    revoked = True
    session = service.session(user, project, snapshot.id)
    until(lambda: session.snapshot(0).status == 'failed')
    assert 'Project access revoked' in (session.snapshot(0).error or '')
    until(lambda: not session.thread.is_alive())
    service.require_idle(user, project)


def test_output_is_bounded_and_stale_input_is_rejected(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, _ = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    payload = terminal.TerminalStart(workspace_id=RepositoryEditor(current, user, project).tree().workspace_id, allow_execution=True)
    first = service.start(user, project, payload, lambda: None)
    session = service.session(user, project, first.id)
    session.append('a' * 300_000)
    snapshot = session.snapshot(0)
    assert len(snapshot.output) <= 262_144
    assert snapshot.start_offset > 0
    assert session.snapshot(snapshot.next_offset).output == ''
    session.stop()
    second = service.start(user, project, payload, lambda: None)
    assert second.id != first.id
    with pytest.raises(ApiProblem):
        service.session(user, project, first.id)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX job control boundary')
def test_background_process_is_killed_after_shell_exit(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, root = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id, allow_execution=True,
    ), lambda: None)
    session = service.session(user, project, snapshot.id)
    session.write('sleep 120 & echo $! > child.pid\r')
    until(lambda: (root / 'child.pid').exists())
    child = psutil.Process(int((root / 'child.pid').read_text()))
    session.write('exit\r')
    until(lambda: session.snapshot(0).status == 'exited')
    assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE


@pytest.mark.skipif(os.name == 'nt', reason='POSIX nonblocking input boundary')
def test_backpressure_preserves_input_and_keeps_session_alive(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, root = workspace
    (root / 'reader.py').write_text('import os, time, tty\nfrom pathlib import Path\ntty.setraw(0)\nPath("ready").touch()\ntime.sleep(.4)\nresult = b""\nwhile len(result) < 60000:\n    result += os.read(0, 8192)\nPath("received").write_bytes(result)\n')
    service = terminal.TerminalManager(current)
    current.terminals = service
    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id, allow_execution=True,
    ), lambda: None)
    session = service.session(user, project, snapshot.id)
    session.write(f'"{sys.executable}" reader.py\r')
    until(lambda: (root / 'ready').exists())
    writer = threading.Thread(target=lambda: session.write('abc123' * 10000))
    writer.start()
    writer.join(timeout=5)
    until(lambda: (root / 'received').exists())
    assert (root / 'received').read_bytes() == b'abc123' * 10000
    assert session.snapshot(0).status == 'running'


@pytest.mark.skipif(os.name == 'nt', reason='Bash prompt protocol')
def test_prompt_tracks_real_branch_and_failure_without_evaluating_branch_name(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, root = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id, allow_execution=True,
    ), lambda: None)
    session = service.session(user, project, snapshot.id)
    until(lambda: ' git main ' in re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', session.snapshot(0).output))
    session.write("git symbolic-ref HEAD 'refs/heads/$(touch${IFS}prompt-injected)'\rfalse\r")
    until(lambda: '\x1b[1;31m❯' in session.snapshot(0).output)
    assert '$(touch${IFS}prompt-injected)' in session.snapshot(0).output
    assert not (root / 'prompt-injected').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows pipe cancellation boundary')
def test_close_unblocks_windows_input_when_shell_is_suspended(workspace: tuple[DesktopWorkspace, UUID, UUID, Path]) -> None:
    current, user, project, _ = workspace
    service = terminal.TerminalManager(current)
    current.terminals = service
    snapshot = service.start(user, project, terminal.TerminalStart(
        workspace_id=RepositoryEditor(current, user, project).tree().workspace_id, allow_execution=True,
    ), lambda: None)
    session = service.session(user, project, snapshot.id)
    until(lambda: '❯' in session.snapshot(0).output)
    process = psutil.Process(session.process.pid)
    process.suspend()

    def write() -> None:
        try:
            for _ in range(128):
                session.write('x' * 8192)
        except ApiProblem:
            return

    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    time.sleep(.2)
    try:
        session.stop()
        writer.join(timeout=2)
        assert not writer.is_alive()
        assert session.snapshot(0).status == 'stopped'
    finally:
        if process.is_running():
            process.kill()
