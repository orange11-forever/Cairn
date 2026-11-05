import subprocess
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from sqlalchemy import text

from .authorization_helpers import seed_actor
from .test_desktop_workspace_api import DesktopFixture, desktop_client, oauth_client
from .test_oauth_api import ORIGIN, password_login

__all__ = ['desktop_client', 'oauth_client']


@pytest.mark.integration
def test_terminal_contract_csrf_reconnect_logout_and_project_binding(
    desktop_client: DesktopFixture, tmp_path: Path, database: Database,
) -> None:
    client, workspace, _, _, clock = desktop_client
    headers = password_login(client)
    project = client.post('/api/v1/projects', json={'name': 'Terminal contract'}, headers=headers).json()['id']
    root = tmp_path.parent / ('terminal-' + str(uuid4()))
    root.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    base = f'/api/v1/desktop/projects/{project}'
    assert client.put(base + '/repository', json={'localPath': str(root)}, headers=headers).status_code == 200
    body = {'workspaceId': client.get(base + '/files').json()['workspaceId'], 'allowExecution': True}
    assert client.get(base + '/terminal').json() is None
    assert client.post(base + '/terminal', json=body, headers={'Origin': ORIGIN}).status_code == 403
    assert client.post(base + '/terminal', json={**body, 'allowExecution': False}, headers=headers).status_code == 422
    response = client.post(base + '/terminal', json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Request-ID']
    snapshot = response.json()
    with database.session_factory() as audit_session:
        restores = audit_session.scalar(text("SELECT count(*) FROM audit_logs WHERE action = 'auth.session_restored'"))
    route = base + '/terminal/' + snapshot['id']
    try:
        assert client.post(route + '/input', json={'data': 'echo unsafe\r'}, headers={'Origin': ORIGIN}).status_code == 403
        assert client.post(route + '/input', json={'data': '🙂' * 3000}, headers=headers).status_code == 422
        assert client.post(route + '/resize', json={'cols': 0, 'rows': 24}, headers=headers).status_code == 422
        assert client.post(route + '/resize', json={'cols': 90, 'rows': 28}, headers=headers).status_code == 204
        assert client.post(route + '/input', json={'data': "printf '\\033[31mHELLO-PTY\\033[0m\\n'\r"}, headers=headers).status_code == 204
        current = snapshot
        for _ in range(80):
            current = client.get(base + '/terminal').json()
            if '\x1b[31mHELLO-PTY\x1b[0m' in current['output']:
                break
            time.sleep(.03)
        assert '\x1b[31mHELLO-PTY\x1b[0m' in current['output']
        assert current['id'] == snapshot['id']
        assert client.get(base + '/terminal', params={'after': current['nextOffset']}).json()['startOffset'] == current['nextOffset']
        with database.session_factory() as audit_session:
            assert audit_session.scalar(text("SELECT count(*) FROM audit_logs WHERE action = 'auth.session_restored'")) == restores
        rejected = client.delete(base + '/repository', headers=headers)
        assert rejected.status_code == 409
        assert rejected.json()['traceId'] == rejected.headers['X-Request-ID']
        assert client.post(base + '/terminal/' + str(uuid4()) + '/input', json={'data': 'x'}, headers=headers).status_code == 404
        assert client.post('/api/v1/logout', headers=headers).status_code == 204
        clock[0] += 3
        assert client.get(base + '/terminal').status_code == 401
        assert workspace.terminals
        terminal = next(iter(workspace.terminals.sessions.values()))
        for _ in range(100):
            if terminal.snapshot(0).status == 'failed':
                break
            time.sleep(.03)
        assert terminal.snapshot(0).status == 'failed'
    finally:
        if workspace.terminals:
            workspace.terminals.close()


@pytest.mark.integration
def test_terminal_requires_write_permission_even_with_own_binding(
    desktop_client: DesktopFixture, database: Database, tmp_path: Path,
) -> None:
    client, workspace, _, _, _ = desktop_client
    headers = password_login(client)
    identity = client.get('/api/v1/session').json()
    project = client.post('/api/v1/projects', json={'name': 'Terminal access'}, headers=headers).json()['id']
    viewer = seed_actor(database, MembershipRole.VIEWER, UUID(identity['organization']['id']))
    root = tmp_path.parent / ('terminal-viewer-' + str(uuid4()))
    root.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    workspace.bind_local(viewer.user_id, UUID(project), str(root))
    client.post('/api/v1/logout', headers=headers)
    login = client.post('/api/v1/login', json={'email': viewer.email, 'password': viewer.password}, headers={'Origin': ORIGIN})
    headers = {'Origin': ORIGIN, 'X-CSRF-Token': login.json()['csrfToken']}
    base = f'/api/v1/desktop/projects/{project}'
    response = client.post(base + '/terminal', json={'workspaceId': 'a' * 64, 'allowExecution': True}, headers=headers)
    assert response.status_code == 404
    assert response.json()['traceId'] == response.headers['X-Request-ID']
    assert client.get(base + '/terminal').status_code == 404
