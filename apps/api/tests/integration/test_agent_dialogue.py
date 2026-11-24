from copy import deepcopy
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_models import AnswerModelOption, ConfiguredAnswerModel
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings
from cairn_api.projects.models import Project, Task
from cairn_api.projects.operation_models import ProjectOperation
from fastapi import FastAPI
from sqlalchemy import delete, func, select, update

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_project_conversations import assert_error
from .test_project_operations import OperationProvider, OperationsFixture, operations

__all__ = ["operations"]
BASE = "/api/v1/agent-dialogue"


def agent(operations: OperationsFixture, database: Database) -> dict[str, str]:
    _, actor, pid, _, _ = operations
    aid = uuid4()
    with database.session_factory.begin() as session:
        session.add(KnowledgeAssistantSettings(
            id=aid, org_id=actor.organization_id, project_id=pid, owner_id=actor.user_id,
            name="项目管家", instructions="先说明再执行", enabled_skill_ids=[], revision=1, is_active=True,
        ))
    return {"originProjectId": str(pid), "assistantId": str(aid)}


def preview(fixture: OperationsFixture, source: dict[str, Any], target: UUID | None = None) -> dict[str, Any]:
    client, _, pid, _, _ = fixture
    response = client.post(BASE + "/preview", json={
        "agent": source, "targetProjectId": str(target or pid), "intent": "按我的要求创建项目或任务",
    })
    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"]
    return {"operationId": str(uuid4()), "confirmed": True, "preview": response.json()}


def query(source: dict[str, Any], target: UUID | str | None = None) -> dict[str, Any]:
    return {"origin_project_id": source["originProjectId"], **({"assistant_id": source["assistantId"]} if source["assistantId"] is not None else {}),
            **({"target_project_id": str(target)} if target else {})}


@pytest.mark.integration
def test_pinned_agent_creates_project_then_manages_it_with_private_receipts(
    database: Database, operations: OperationsFixture,
) -> None:
    client, _, pid, _, provider = operations
    source = agent(operations, database)
    provider.action = {"type": "create_project", "name": "Agent 新项目"}
    creation = preview(operations, source)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0
        before = session.scalar(select(func.count()).select_from(Project))
    assert client.post(BASE + "/operations", json={**creation, "confirmed": False}).status_code == 422
    saved = client.post(BASE + "/operations", json=creation)
    assert saved.status_code == 201, saved.text
    result = saved.json()
    target = UUID(result["projectId"])
    assert target != pid and result["result"]["name"] == "Agent 新项目"
    assert client.post(BASE + "/operations", json=creation).status_code == 200
    recovered = client.get(BASE + "/operations/" + creation["operationId"], params=query(source, pid))
    assert recovered.json() == result
    assert client.get(f"/api/v1/projects/{target}/operations").json()["items"] == [result]
    assert client.get(BASE + "/operations", params=query(source, target)).json()["items"] == [result]
    provider.action = {"type": "create_task", "title": "同一 Agent 的任务"}
    task = preview(operations, source, target)
    assert task["preview"]["assistant"]["name"] == "项目管家"
    assert provider.requests[-1][2].instructions == "先说明再执行"
    applied = client.post(BASE + "/operations", json=task)
    assert applied.status_code == 201, applied.text
    assert applied.json()["projectId"] == str(target)
    assert client.post(BASE + "/operations", json=task).json() == applied.json()
    changed = deepcopy(task)
    changed["preview"]["preview"]["suggestion"]["action"]["title"] = "另一个任务"
    assert_error(client.post(BASE + "/operations", json=changed), 409, "operation_conflict")
    other_agent = {"originProjectId": str(pid), "assistantId": None}
    assert client.get(BASE + "/operations", params=query(other_agent, target)).json()["items"] == []
    assert_error(client.get(BASE + "/operations/" + task["operationId"], params=query(other_agent, target)), 404, "not_found")
    with database.session_factory() as session:
        assert before is not None
        assert session.scalar(select(func.count()).select_from(Project)) == before + 1
        assert session.scalar(select(func.count()).select_from(Task).where(Task.project_id == target)) == 1
        assert session.scalar(select(func.count()).select_from(KnowledgeAssistantSettings).where(
            KnowledgeAssistantSettings.project_id == target)) == 0


@pytest.mark.integration
def test_active_profile_switch_does_not_change_pinned_guidance_or_confirmation(
    database: Database, operations: OperationsFixture,
) -> None:
    client, actor, pid, _, provider = operations
    source = agent(operations, database)
    payload = preview(operations, source)
    with database.session_factory.begin() as session:
        session.execute(update(KnowledgeAssistantSettings).where(
            KnowledgeAssistantSettings.id == UUID(source["assistantId"])).values(is_active=False))
        session.add(KnowledgeAssistantSettings(
            id=uuid4(), org_id=actor.organization_id, project_id=pid, owner_id=actor.user_id,
            name="别的 Agent", instructions="其他行为", enabled_skill_ids=[], revision=2, is_active=True,
        ))
    assert client.post(BASE + "/operations", json=payload).status_code == 201
    preview(operations, source)
    assert provider.requests[-1][2].assistant_name == "项目管家"
    assert provider.requests[-1][2].instructions == "先说明再执行"
    builtin = preview(operations, {"originProjectId": str(pid), "assistantId": None})
    assert builtin["preview"]["assistant"]["name"] == "岑宁"
    assert provider.requests[-1][2].instructions == ""
    builtin["operationId"] = payload["operationId"]
    assert_error(client.post(BASE + "/operations", json=builtin), 409, "operation_conflict")


@pytest.mark.integration
@pytest.mark.parametrize("when", ["during_model", "before_apply"])
def test_source_access_is_rechecked_at_the_changed_boundaries(
    database: Database, operations: OperationsFixture, when: str,
) -> None:
    client, _, pid, _, provider = operations
    source = agent(operations, database)

    def revoke() -> None:
        with database.session_factory.begin() as session:
            session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == pid))

    if when == "during_model":
        provider.change = revoke
        response = client.post(BASE + "/preview", json={"agent": source, "targetProjectId": str(pid), "intent": "创建任务"})
    else:
        payload = preview(operations, source)
        revoke()
        response = client.post(BASE + "/operations", json=payload)
    assert_error(response, 404, "not_found")
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0


@pytest.mark.integration
def test_changed_source_configuration_requires_a_new_preview(database: Database, operations: OperationsFixture) -> None:
    client, _, _, _, _ = operations
    source = agent(operations, database)
    payload = preview(operations, source)
    with database.session_factory.begin() as session:
        session.execute(update(KnowledgeAssistantSettings).where(
            KnowledgeAssistantSettings.id == UUID(source["assistantId"])).values(instructions="行为已变"))
    assert_error(client.post(BASE + "/operations", json=payload), 409, "assistant_changed")


@pytest.mark.integration
def test_source_profiles_are_private_and_foreign_ids_never_fall_back(
    database: Database, test_database_url: str, operations: OperationsFixture,
) -> None:
    client, actor, pid, _, provider = operations
    source = agent(operations, database)
    other = seed_actor(database, MembershipRole.OWNER, actor.organization_id)
    with knowledge_client(knowledge_settings(test_database_url), database, other,
                          MemoryObjectStore(), answer_provider=provider) as outsider:
        assert_error(outsider.post(BASE + "/preview", json={"agent": source, "targetProjectId": str(pid), "intent": "创建任务"}), 404, "not_found")
    source["assistantId"] = str(uuid4())
    assert_error(client.post(BASE + "/preview", json={"agent": source, "targetProjectId": str(pid), "intent": "创建任务"}), 404, "not_found")
    assert provider.requests == []


@pytest.mark.integration
def test_coding_dispatch_requires_workspace_confirmation(database: Database, operations: OperationsFixture) -> None:
    client, _, _, tid, provider = operations
    source = agent(operations, database)
    provider.action = {"type": "dispatch_task", "taskId": str(tid), "assistantId": source["assistantId"]}
    payload = preview(operations, source)
    assert client.post(BASE + "/operations", json=payload).status_code == 422
    with database.session_factory() as session:
        task = session.get(Task, tid)
        assert task is not None and task.status != "done"
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0


@pytest.mark.integration
def test_pinned_model_is_selected_even_when_another_profile_is_active(
    database: Database, operations: OperationsFixture,
) -> None:
    client, actor, pid, _, default_provider = operations
    source = agent(operations, database)
    pinned_provider = OperationProvider()
    models = cast(FastAPI, client.app).state.answer_models
    models["pinned"] = ConfiguredAnswerModel(
        info=AnswerModelOption(id="pinned", name="专属模型", model="synthetic-pinned", protocol="openai-compatible"),
        provider=pinned_provider,
    )
    with database.session_factory.begin() as session:
        session.execute(update(KnowledgeAssistantSettings).where(
            KnowledgeAssistantSettings.id == UUID(source["assistantId"])).values(model_id="pinned", is_active=False))
        session.add(KnowledgeAssistantSettings(
            id=uuid4(), org_id=actor.organization_id, project_id=pid, owner_id=actor.user_id,
            name="当前选择", instructions="不能串入", enabled_skill_ids=[], revision=2, is_active=True,
        ))
    payload = preview(operations, source)
    assert payload["preview"]["preview"]["model"]["id"] == "pinned"
    assert len(pinned_provider.requests) == 1 and default_provider.requests == []
    assert pinned_provider.requests[0][2].assistant_name == "项目管家"


@pytest.mark.integration
@pytest.mark.parametrize("creation", [False, True])
def test_current_target_access_is_required_at_confirmation(
    database: Database, operations: OperationsFixture, creation: bool,
) -> None:
    client, actor, _, _, provider = operations
    source = agent(operations, database)
    from .knowledge_helpers import seed_project

    target = seed_project(database, actor, permission="write")
    if creation:
        provider.action = {"type": "create_project", "name": "不能越权创建"}
    payload = preview(operations, source, target)
    with database.session_factory.begin() as session:
        session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == target))
    assert_error(client.post(BASE + "/operations", json=payload), 404, "not_found")
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0


@pytest.mark.integration
def test_creation_rechecks_live_role_after_model_work(database: Database, operations: OperationsFixture) -> None:
    from cairn_api.organizations.models import Membership

    client, actor, pid, _, provider = operations
    source = agent(operations, database)
    provider.action = {"type": "create_project", "name": "不能越权创建"}

    def demote() -> None:
        with database.session_factory.begin() as session:
            session.execute(update(Membership).where(Membership.id == actor.membership_id).values(role="viewer"))

    provider.change = demote
    assert_error(client.post(BASE + "/preview", json={"agent": source, "targetProjectId": str(pid), "intent": "创建项目"}), 403, "forbidden")


@pytest.mark.integration
def test_recovery_does_not_mix_same_operation_ids_in_different_working_projects(
    database: Database, operations: OperationsFixture,
) -> None:
    from .knowledge_helpers import seed_project

    client, actor, pid, _, _ = operations
    source = agent(operations, database)
    target = seed_project(database, actor, permission="write")
    first = preview(operations, source)
    second = preview(operations, source, target)
    second["operationId"] = first["operationId"]
    results = [client.post(BASE + "/operations", json=payload) for payload in [first, second]]
    assert [result.status_code for result in results] == [201, 201]
    for working, result in zip([pid, target], results, strict=True):
        recovered = client.get(BASE + "/operations/" + first["operationId"], params=query(source, working))
        assert recovered.status_code == 200 and recovered.json() == result.json()


@pytest.mark.integration
@pytest.mark.parametrize("creation_first", [True, False])
def test_one_receipt_id_cannot_switch_between_creation_and_task_in_the_same_dialogue(
    database: Database, operations: OperationsFixture, creation_first: bool,
) -> None:
    client, _, pid, _, provider = operations
    source = agent(operations, database)
    actions = [{"type": "create_project", "name": "确认的新项目"},
               {"type": "create_task", "title": "确认的新任务"}]
    if not creation_first:
        actions.reverse()
    provider.action = actions[0]
    first = preview(operations, source)
    saved = client.post(BASE + "/operations", json=first)
    assert saved.status_code == 201, saved.text
    provider.action = actions[1]
    second = preview(operations, source)
    second["operationId"] = first["operationId"]
    assert_error(client.post(BASE + "/operations", json=second), 409, "operation_conflict")
    recovered = client.get(BASE + "/operations/" + first["operationId"], params=query(source, pid))
    assert recovered.json() == saved.json()
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 1
