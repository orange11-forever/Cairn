import base64
from io import BytesIO
from uuid import uuid4

import pytest
from cairn_api.db.session import Database
from PIL import Image

from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_multiple_assistants import AssistantProvider
from .test_project_conversations import create, seed_conversation_boundary


def avatar_png(color: str = "blue") -> str:
    output = BytesIO()
    Image.new("RGB", (128, 128), color=color).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


@pytest.mark.integration
def test_custom_names_and_avatars_persist_independently_and_keep_historical_name(database: Database, test_database_url: str) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    blue, red = avatar_png("blue"), avatar_png("red")
    config: dict[str, object] = {"name": "蓝色计划员", "instructions": "先计划", "enabledSkillIds": [], "expectedRevision": 0, "avatarDataUrl": blue}
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore(), SearchEmbedding(), AssistantProvider()) as client:
        first_response = client.put(prefix + "/assistant-settings", json=config)
        assert first_response.status_code == 200
        assert "X-Request-ID" in first_response.headers
        first = first_response.json()
        assert first["avatarDataUrl"] == blue
        cid = create(client, prefix)
        turn = client.post(f"{prefix}/conversations/{cid}/turns", json={"id": str(uuid4()), "question": "何时交付？", "expectedRevision": 1, "assistantRevision": 1})
        assert turn.status_code == 200
        renamed = client.put(prefix + "/assistant-settings", json={**config, "expectedRevision": 1, "name": "新的名字", "avatarDataUrl": red})
        assert renamed.status_code == 200
        assert renamed.json()["revision"] == 2
        assert client.get(f"{prefix}/conversations/{cid}").json()["turns"][0]["assistantName"] == "蓝色计划员"
        second = client.post(prefix + "/assistants", json={**config, "expectedRevision": 2, "name": "独立复核员"}).json()
        assert second["id"] != first["id"] and second["avatarDataUrl"] == blue
        response = client.post(f"{prefix}/assistants/{first['id']}/select", json={"expectedRevision": 3})
        assert response.json()["avatarDataUrl"] == red and response.json()["name"] == "新的名字"
        omitted = {k: v for k, v in config.items() if k != "avatarDataUrl"}
        assert client.put(prefix + "/assistant-settings", json={**omitted, "expectedRevision": 4}).json()["avatarDataUrl"] == red
        invalid = client.put(prefix + "/assistant-settings", json={**config, "expectedRevision": 5, "avatarDataUrl": "https://example.com/avatar.png"})
        assert invalid.status_code == 422
        assert invalid.json()["traceId"] == invalid.headers["X-Request-ID"]
        assert client.get(prefix + "/assistant-settings").json()["avatarDataUrl"] == red
        removed = client.put(prefix + "/assistant-settings", json={**config, "expectedRevision": 5, "avatarDataUrl": None})
        assert removed.status_code == 200 and removed.json()["avatarDataUrl"] is None
        profiles = {item["id"]: item for item in client.get(prefix + "/assistants").json()["items"]}
        assert profiles[first["id"]]["avatarDataUrl"] is None
        assert profiles[second["id"]]["avatarDataUrl"] == blue
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore(), SearchEmbedding(), AssistantProvider()) as client:
        profiles = {item["id"]: item for item in client.get(prefix + "/assistants").json()["items"]}
        assert profiles[second["id"]]["avatarDataUrl"] == blue
        assert profiles[first["id"]]["avatarDataUrl"] is None
