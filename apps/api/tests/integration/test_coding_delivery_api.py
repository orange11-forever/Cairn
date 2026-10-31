import base64
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_models import AnswerModelOption, ConfiguredAnswerModel
from cairn_api.organizations.models import Membership
from cairn_api.seed import DEMO_MEMBERSHIP_ID
from cairn_api.workspace.coding_schemas import CodingStep
from cairn_api.workspace.local import DesktopWorkspace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .test_coding_api import CodingModel
from .test_oauth_api import oauth_client, password_login

__all__ = ['oauth_client']


class DeliveryModel(CodingModel):
    def coding_step(self, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep:
        history = cast(list[object], context['history'])
        actions = [
            {'kind': 'read_file', 'path': 'main.py'},
            {'kind': 'write_file', 'path': 'main.py', 'content': 'value = 1\n', 'create': False},
            {'kind': 'run_command', 'argv': [sys.executable, '-c', 'from main import value; assert value == 1'], 'purpose': 'test', 'timeout_seconds': 10},
            {'kind': 'finish', 'summary': 'Value verified'},
        ]
        return CodingStep.model_validate({'message': 'Execute fixture step', 'action': actions[len(history)]})


@pytest.mark.integration
def test_delivery_api_owner_csrf_stale_snapshot_and_commit_contract(oauth_client: TestClient, tmp_path: Path, database: Database) -> None:
    client = oauth_client
    headers = password_login(client)
    project = client.post('/api/v1/projects', json={'name': 'Delivery API'}, headers=headers).json()['id']
    root, data = tmp_path / 'repo', tmp_path / 'data'
    root.mkdir(); data.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    (root / 'main.py').write_text('value = 0\n')
    subprocess.run(['git', '-C', str(root), 'add', 'main.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'baseline'], check=True, capture_output=True)
    app = cast(FastAPI, client.app)
    workspace = DesktopWorkspace(data, Path('/usr/bin/git'), None, base64.b64encode, base64.b64decode)
    app.state.desktop_workspace = workspace
    app.state.answer_models = {'default': ConfiguredAnswerModel(AnswerModelOption(id='default', name='Fixture', model='fixture', protocol='openai-compatible'), DeliveryModel())}
    base = f'/api/v1/desktop/projects/{project}'
    assert client.put(base + '/repository', json={'localPath': str(root)}, headers=headers).status_code == 200
    tree = client.get(base + '/files').json()
    response = client.post(base + '/coding-runs', json={'workspaceId': tree['workspaceId'], 'task': 'Fix value', 'assistantRevision': 0, 'allowWrites': True}, headers=headers)
    assert response.status_code == 202, response.text
    run_id = response.json()['id']
    route = base + '/coding-runs/' + run_id
    try:
        current = response.json()
        for _ in range(150):
            current = client.get(route).json()
            if current['status'] == 'awaiting_approval':
                break
            time.sleep(.02)
        assert current['status'] == 'awaiting_approval', current
        assert client.post(route + '/decision', json={'eventId': current['pendingCommand']['eventId'], 'approved': True, 'verify': True}, headers=headers).status_code == 200
        for _ in range(150):
            current = client.get(route).json()
            if current['status'] == 'succeeded':
                break
            time.sleep(.02)
        assert current['status'] == 'succeeded', current
        delivery = route + '/delivery'
        preview = client.get(delivery)
        assert preview.status_code == 200 and preview.headers['Cache-Control'] == 'no-store'
        assert 'assert value == 1' in preview.json()['suggestedBody']
        body = {'snapshotId': preview.json()['snapshotId'], 'message': 'Fix value', 'authorName': 'Test Author', 'authorEmail': 'test@example.com'}
        assert client.post(delivery + '/commit', json=body).status_code == 403
        invalid = client.post(delivery + '/target', json={'baseBranch': 'main\x00'}, headers=headers)
        assert invalid.status_code == 422
        assert invalid.json()['traceId'] == invalid.headers['X-Request-ID']
        stale = client.post(delivery + '/commit', json={**body, 'snapshotId': '0' * 64}, headers=headers)
        assert stale.status_code == 409 and stale.json()['code'] == 'coding_delivery_changed'
        # READ permission still allows the preview, but cannot create a commit.
        with database.session_factory.begin() as session:
            member = session.get(Membership, DEMO_MEMBERSHIP_ID)
            assert member
            membership_id = member.id
            member.role = 'viewer'
        denied = client.post(delivery + '/commit', json=body, headers=headers)
        assert denied.status_code == 404
        with database.session_factory.begin() as session:
            member = session.get(Membership, membership_id)
            assert member
            member.role = 'owner'
        saved = client.post(delivery + '/commit', json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result['status'] == 'succeeded' and result['delivery']['phase'] == 'committed'
        sha = result['delivery']['commitSha']
        assert len(sha) == 40 and result['delivery']['authorEmail'] == 'test@example.com'
        assert saved.headers['Cache-Control'] == 'no-store' and saved.headers['X-Request-ID']
        assert client.post(delivery + '/commit', json=body, headers=headers).status_code == 409
        assert client.get(delivery).json()['delivery']['commitSha'] == sha
        assert (root / 'main.py').read_text() == 'value = 0\n'
        contract = client.get('/openapi.json').json()['paths']['/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery/commit']['post']
        assert '200' in contract['responses'] and 'X-Request-ID' in contract['responses']['200']['headers']
    finally:
        if workspace.coding:
            workspace.coding.close()
