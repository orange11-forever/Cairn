import base64
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_models import AnswerModelOption, ConfiguredAnswerModel
from cairn_api.knowledge.answer_provider import AnswerEvidence, ProviderAnswer
from cairn_api.workspace.coding_schemas import CodingStep
from cairn_api.workspace.local import DesktopWorkspace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .authorization_helpers import seed_actor
from .test_oauth_api import oauth_client, password_login

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
def test_coding_api_csrf_owner_approval_and_isolated_editor(oauth_client: TestClient, tmp_path: Path) -> None:
    client = oauth_client
    headers = password_login(client)
    project = client.post('/api/v1/projects', json={'name': 'Coding API'}, headers=headers).json()['id']
    root, data = tmp_path / 'repo', tmp_path / 'data'
    root.mkdir(); data.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    (root / 'main.py').write_text('print(1)\n')
    subprocess.run(['git', '-C', str(root), 'add', 'main.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'baseline'], check=True, capture_output=True)
    app = cast(FastAPI, client.app)
    workspace = DesktopWorkspace(data, Path('/usr/bin/git'), None, base64.b64encode, base64.b64decode)
    app.state.desktop_workspace = workspace
    app.state.answer_models = {'default': ConfiguredAnswerModel(
        AnswerModelOption(id='default', name='Coding fixture', model='fixture', protocol='openai-compatible'), CodingModel())}
    base = f'/api/v1/desktop/projects/{project}'
    assert client.put(base + '/repository', json={'localPath': str(root)}, headers=headers).status_code == 200
    tree = client.get(base + '/files').json()
    task_response = client.post(f'/api/v1/projects/{project}/tasks', json={
        'title': 'Check arithmetic', 'expectedProjectRevision': 1}, headers=headers)
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    source = {'taskId': task['id'], 'revision': task['revision']}
    body = {'workspaceId': tree['workspaceId'], 'task': 'Check arithmetic', 'assistantRevision': 0,
            'allowWrites': True, 'sourceTask': source}
    stale = client.post(base + '/coding-runs', json={**body, 'sourceTask': {**source, 'revision': source['revision'] + 1}}, headers=headers)
    assert stale.status_code == 409, stale.text
    assert stale.json()['code'] == 'coding_task_changed'
    other_project = client.post('/api/v1/projects', json={'name': 'Other project'}, headers=headers).json()['id']
    other_task = client.post(f'/api/v1/projects/{other_project}/tasks', json={
        'title': 'Unrelated task', 'expectedProjectRevision': 1}, headers=headers).json()
    outside = client.post(base + '/coding-runs', json={**body, 'sourceTask': {
        'taskId': other_task['id'], 'revision': other_task['revision']}}, headers=headers)
    assert outside.status_code == 404, outside.text
    assert client.get(base + '/coding-runs').json()['items'] == []
    assert client.post(base + '/coding-runs', json=body, headers={'Origin': headers['Origin']}).status_code == 403
    response = client.post(base + '/coding-runs', json=body, headers=headers)
    assert response.status_code == 202, response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Request-ID']
    assert response.json()['sourceTask'] == source
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
        saved = client.put(base + '/file', json={**doc, 'content': 'overwritten'}, headers=headers)
        assert saved.status_code == 200
        assert (Path(current['localPath']) / 'main.py').read_text() == 'print(1)\n'
        blocked = client.delete(base + '/repository', headers=headers)
        assert blocked.status_code == 409
        assert blocked.json()['traceId'] == blocked.headers['X-Request-ID']
        queued = client.post(base + '/coding-runs', json=body, headers=headers)
        assert queued.status_code == 202 and queued.json()['status'] == 'queued'
        assert client.post(base + '/coding-runs/' + queued.json()['id'] + '/cancel', headers=headers).status_code == 200
        rejected = client.post(route + '/decision', json={'eventId': current['pendingCommand']['eventId'] + 1, 'approved': True}, headers=headers)
        assert rejected.status_code == 409
        cancelled = client.post(route + '/cancel', headers=headers)
        assert cancelled.status_code == 200
        for _ in range(100):
            if client.get(route).json()['status'] == 'cancelled':
                break
            time.sleep(0.02)
        assert client.get(route).json()['status'] == 'cancelled'
        assert (root / 'main.py').read_text() == 'overwritten'
        client.post('/api/v1/logout', headers=headers)
        assert client.get(route).status_code == 401
    finally:
        if workspace.coding:
            workspace.coding.close()


@pytest.mark.integration
def test_parallel_api_snapshots_selected_agents_overview_and_concurrency(oauth_client: TestClient, tmp_path: Path, database: Database) -> None:
    client = oauth_client
    headers = password_login(client)
    project = client.post('/api/v1/projects', json={'name': 'Parallel snapshot'}, headers=headers).json()['id']
    root, data = tmp_path / 'repo', tmp_path / 'data'
    root.mkdir(); data.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    (root / 'main.py').write_text('value = 1\n')
    subprocess.run(['git', '-C', str(root), 'add', 'main.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'baseline'], check=True, capture_output=True)
    app = cast(FastAPI, client.app)
    workspace = DesktopWorkspace(data, Path('/usr/bin/git'), None, base64.b64encode, base64.b64decode)
    app.state.desktop_workspace = workspace
    app.state.answer_models = {'default': ConfiguredAnswerModel(
        AnswerModelOption(id='default', name='Coding fixture', model='fixture', protocol='openai-compatible'), CodingModel())}
    base = f'/api/v1/desktop/projects/{project}'
    knowledge = f'/api/v1/projects/{project}/knowledge'
    assert client.put(base + '/repository', json={'localPath': str(root)}, headers=headers).status_code == 200
    tree = client.get(base + '/files').json()
    config: dict[str, object] = {'name': 'Agent A', 'instructions': 'Check first task', 'enabledSkillIds': [], 'expectedRevision': 0}
    a = client.put(knowledge + '/assistant-settings', json=config, headers=headers).json()
    body = {'workspaceId': tree['workspaceId'], 'task': 'First task', 'assistantId': a['id'], 'assistantRevision': a['revision'], 'allowWrites': True}
    first = client.post(base + '/coding-runs', json=body, headers=headers).json()
    try:
        b = client.post(knowledge + '/assistants', json={**config, 'name': 'Agent B', 'expectedRevision': a['revision']}, headers=headers).json()
        response = client.post(base + '/coding-runs', json={**body, 'task': 'Second task', 'assistantId': b['id'], 'assistantRevision': b['revision']}, headers=headers)
        assert response.status_code == 202, response.text
        second = response.json()
        one, two = first, second
        for _ in range(150):
            one = client.get(base + '/coding-runs/' + first['id']).json()
            two = client.get(base + '/coding-runs/' + second['id']).json()
            if one['status'] == two['status'] == 'awaiting_approval':
                break
            time.sleep(0.02)
        assert one['status'] == two['status'] == 'awaiting_approval'
        assert one['assistantName'] == 'Agent A' and one['assistantRevision'] == a['revision']
        assert one['localPath'] != two['localPath'] and one['branch'] != two['branch']
        # Exercise the worker's authorization callback AFTER changing the selected profile.
        assert client.post(base + '/coding-runs/' + first['id'] + '/decision', json={
            'eventId': one['pendingCommand']['eventId'], 'approved': True, 'verify': True}, headers=headers).status_code == 200
        for _ in range(100):
            one = client.get(base + '/coding-runs/' + first['id']).json()
            if any(event['kind'] == 'command_result' for event in one['events']):
                break
            time.sleep(0.02)
        assert any(event['kind'] == 'command_result' and event['exitCode'] == 0 for event in one['events'])
        overview = client.get('/api/v1/desktop/coding-runs')
        assert overview.status_code == 200 and overview.headers['Cache-Control'] == 'no-store'
        assert {(item['projectName'], item['assistantName']) for item in overview.json()['items']} == {('Parallel snapshot', 'Agent A'), ('Parallel snapshot', 'Agent B')}
        assert client.put('/api/v1/desktop/coding-concurrency', json={'limit': 1}).status_code == 403
        invalid = client.put('/api/v1/desktop/coding-concurrency', json={'limit': 5}, headers=headers)
        assert invalid.status_code == 422 and invalid.json()['traceId'] == invalid.headers['X-Request-ID']
        assert client.put('/api/v1/desktop/coding-concurrency', json={'limit': 1}, headers=headers).json() == {'limit': 1}
        assert client.get('/api/v1/desktop/coding-runs').json()['concurrency'] == 1
        assert client.get(base + '/coding-runs/' + second['id']).json()['status'] == 'awaiting_approval'
        # A real second account must not see the first account's runs.
        client.post('/api/v1/logout', headers=headers)
        other = client.get('/api/v1/desktop/coding-runs')
        assert other.status_code == 401
        actor = seed_actor(database, MembershipRole.MEMBER)
        assert client.post('/api/v1/auth/login-context', headers={'Origin': headers['Origin']}).status_code == 204
        response = client.post('/api/v1/login', headers={'Origin': headers['Origin']},
                               json={'email': actor.email, 'password': actor.password})
        assert response.status_code == 200, response.text
        other_headers = {'Origin': headers['Origin'], 'X-CSRF-Token': response.json()['csrfToken']}
        assert client.get('/api/v1/desktop/coding-runs').json()['items'] == []
        assert client.get(base + '/coding-runs/' + first['id']).status_code == 404
        assert client.put('/api/v1/desktop/coding-concurrency', json={'limit': 4}, headers=other_headers).status_code == 403
    finally:
        if workspace.coding:
            workspace.coding.close()
