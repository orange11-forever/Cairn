import base64
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from cairn_api.knowledge.answer_models import AnswerModelOption, ConfiguredAnswerModel
from cairn_api.knowledge.answer_provider import AnswerEvidence, ProviderAnswer
from cairn_api.workspace.coding_schemas import CodingStep
from cairn_api.workspace.local import DesktopWorkspace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.tests.integration.test_oauth_api import oauth_client, password_login

__all__ = ['oauth_client']


class CodingModel:
    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        raise AssertionError('Coding must not call the knowledge-answer parser')

    def coding_step(self, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep:
        return CodingStep.model_validate({'message': 'Run the test', 'action': {
            'kind': 'run_command', 'argv': [sys.executable, '-c', 'assert 1 + 1 == 2'],
            'purpose': 'test', 'timeoutSeconds': 10,
        }})


@pytest.mark.integration
def test_coding_api_csrf_owner_approval_and_active_editor_guard(oauth_client: TestClient, tmp_path: Path) -> None:
    client = oauth_client
    headers = password_login(client)
    project = client.post('/api/v1/projects', json={'name': 'Coding API'}, headers=headers).json()['id']
    root, data = tmp_path / 'repo', tmp_path / 'data'
    root.mkdir(); data.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    (root / 'main.py').write_text('print(1)\n')
    app = cast(FastAPI, client.app)
    workspace = DesktopWorkspace(data, Path('/usr/bin/git'), None, base64.b64encode, base64.b64decode)
    app.state.desktop_workspace = workspace
    app.state.answer_models = {'default': ConfiguredAnswerModel(
        AnswerModelOption(id='default', name='Coding fixture', model='fixture', protocol='openai-compatible'), CodingModel())}
    base = f'/api/v1/desktop/projects/{project}'
    assert client.put(base + '/repository', json={'localPath': str(root)}, headers=headers).status_code == 200
    tree = client.get(base + '/files').json()
    body = {'workspaceId': tree['workspaceId'], 'task': 'Check arithmetic', 'assistantRevision': 0, 'allowWrites': True}
    assert client.post(base + '/coding-runs', json=body, headers={'Origin': headers['Origin']}).status_code == 403
    response = client.post(base + '/coding-runs', json=body, headers=headers)
    assert response.status_code == 202, response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Request-ID']
    run_id = response.json()['id']
    route = base + '/coding-runs/' + run_id
    try:
        current = response.json()
        for _ in range(100):
            current = client.get(route).json()
            if current['status'] == 'awaiting_approval':
                break
            time.sleep(0.02)
        assert current['status'] == 'awaiting_approval', current
        doc = client.get(base + '/file', params={'path': 'main.py'}).json()
        blocked = client.put(base + '/file', json={**doc, 'content': 'overwritten'}, headers=headers)
        assert blocked.status_code == 409 and blocked.json()['code'] == 'coding_run_active'
        assert blocked.json()['traceId'] == blocked.headers['X-Request-ID']
        assert client.delete(base + '/repository', headers=headers).status_code == 409
        assert client.post(base + '/coding-runs', json=body, headers=headers).status_code == 409
        rejected = client.post(route + '/decision', json={'eventId': current['pendingCommand']['eventId'] + 1, 'approved': True}, headers=headers)
        assert rejected.status_code == 409
        cancelled = client.post(route + '/cancel', headers=headers)
        assert cancelled.status_code == 200
        for _ in range(100):
            if client.get(route).json()['status'] == 'cancelled':
                break
            time.sleep(0.02)
        assert client.get(route).json()['status'] == 'cancelled'
        assert (root / 'main.py').read_text() == 'print(1)\n'
        client.post('/api/v1/logout', headers=headers)
        assert client.get(route).status_code == 401
    finally:
        if workspace.coding:
            workspace.coding.close()
