import subprocess
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from cairn_api.knowledge.answer_models import AnswerModelOption, ConfiguredAnswerModel
from cairn_api.knowledge.answer_provider import AnswerEvidence, ProviderAnswer, ProviderParagraph
from fastapi import FastAPI

from apps.api.tests.integration.test_desktop_workspace_api import (
    DesktopFixture,
    desktop_client,
    oauth_client,
)
from apps.api.tests.integration.test_oauth_api import password_login

__all__ = ["desktop_client", "oauth_client"]


class ArchitectureProvider:
    def __init__(self) -> None:
        self.evidence: list[AnswerEvidence] = []
        self.invalid = False
        self.change_file: Path | None = None

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        assert "静态分析" in question
        self.evidence = evidence
        if self.change_file:
            self.change_file.write_text('print("changed during model call")')
        return ProviderAnswer(
            status="answered",
            paragraphs=[
                ProviderParagraph(
                    text="技术栈与入口：Python 服务由 main.py 启动。",
                    citationIds=["unknown" if self.invalid else evidence[0].id],
                )
            ],
        )


@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["success", "invalid-citation", "source-changed", "no-model"])
def test_architecture_reads_real_bound_code_and_checks_model_boundary(
    desktop_client: DesktopFixture, tmp_path: Path, outcome: str
) -> None:
    client, workspace, _, _, _ = desktop_client
    headers = password_login(client)
    project = client.post(
        "/api/v1/projects", json={"name": "Architecture test"}, headers=headers
    ).json()["id"]
    code = tmp_path.parent / ("architecture-" + str(uuid4()))
    code.mkdir()
    subprocess.run(["git", "-C", str(code), "init", "-b", "main"], check=True, capture_output=True)
    (code / "main.py").write_text('print("Python application entry")')
    (code / ".env").write_text("API_KEY=must-not-reach-model")
    binding = client.put(
        f"/api/v1/desktop/projects/{project}/repository",
        json={"localPath": str(code)},
        headers=headers,
    )
    assert binding.status_code == 200
    route = f"/api/v1/desktop/projects/{project}/architecture"
    preview = client.get(route)
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()
    assert snapshot["sources"][0]["path"] == "main.py"
    assert "must-not-reach-model" not in preview.text
    provider = ArchitectureProvider()
    provider.invalid = outcome == "invalid-citation"
    if outcome == "source-changed":
        provider.change_file = code / "main.py"
    cast(FastAPI, client.app).state.answer_models = (
        {}
        if outcome == "no-model"
        else {
            "test": ConfiguredAnswerModel(
                AnswerModelOption(
                    id="test",
                    name="Architecture test model",
                    model="controlled",
                    protocol="openai-compatible",
                ),
                provider,
            )
        }
    )
    payload = {"snapshotDigest": snapshot["digest"], "assistantId": None, "assistantRevision": 0}
    assert (
        client.post(route, json=payload, headers={"Origin": headers["Origin"]}).status_code == 403
    )
    response = client.post(route, json=payload, headers=headers)
    assert (
        response.json().get("traceId", response.headers["X-Request-ID"])
        == response.headers["X-Request-ID"]
    )
    if outcome == "success":
        assert response.status_code == 200, response.text
        assert response.json()["model"]["id"] == "test"
        assert response.json()["snapshot"]["digest"] == snapshot["digest"]
        assert response.json()["paragraphs"][0]["citationIds"] == ["S1"]
        assert "Python application entry" in provider.evidence[0].text
        assert (
            workspace.binding(
                UUID(client.get("/api/v1/session").json()["user"]["id"]), UUID(project)
            )
            is not None
        )
    elif outcome == "invalid-citation":
        assert (
            response.status_code == 502
            and response.json()["code"] == "architecture_invalid_response"
        )
    elif outcome == "source-changed":
        assert response.status_code == 409 and response.json()["code"] == "architecture_changed"
    else:
        assert response.status_code == 503 and response.json()["code"] == "answer_unavailable"
        assert provider.evidence == []
