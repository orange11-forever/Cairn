from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import UUID, uuid4

import pytest
from cairn_api.db.session import Database
from cairn_api.projects.models import Milestone, Project, ProjectStage, Task, TaskDependency
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from .test_projects_api import api_settings, client

__all__ = ["api_settings", "client"]


def seed_graph(client: TestClient, database: Database, count: int = 65) -> tuple[UUID, list[UUID]]:
    created = client.post("/api/v1/projects", json={"name": "完整任务图"})
    assert created.status_code == 201
    project_id = UUID(created.json()["id"])
    ids = [uuid4() for _ in range(count)]
    with database.session_factory.begin() as session:
        project = session.get(Project, project_id)
        assert project is not None
        stage = ProjectStage(
            org_id=project.org_id, project_id=project_id, name="已归档阶段", archived=True
        )
        session.add(stage)
        session.flush()
        milestone = Milestone(
            org_id=project.org_id, project_id=project_id, stage_id=stage.id, name="验收点"
        )
        session.add(milestone)
        session.flush()
        session.add_all(
            [
                Task(
                    id=task_id,
                    org_id=project.org_id,
                    project_id=project_id,
                    stage_id=stage.id,
                    milestone_id=milestone.id,
                    title=f"任务 {index}",
                    status="todo",
                    priority="medium",
                )
                for index, task_id in enumerate(ids)
            ]
        )
        session.flush()
        session.add_all(
            [
                TaskDependency(
                    org_id=project.org_id,
                    project_id=project_id,
                    predecessor_task_id=ids[index],
                    successor_task_id=ids[index + 1],
                )
                for index in range(count - 1)
            ]
        )
    return project_id, ids


@pytest.mark.integration
def test_graph_contains_tasks_beyond_list_page_and_complete_edges(
    client: TestClient, database: Database
):
    project_id, ids = seed_graph(client, database)
    assert len(client.get(f"/api/v1/projects/{project_id}/tasks").json()["items"]) == 50
    response = client.get(
        f"/api/v1/projects/{project_id}/task-graph", headers={"X-Request-ID": "graph-complete"}
    )
    assert response.status_code == 200, response.text
    graph = response.json()
    assert {node["id"] for node in graph["tasks"]} == {str(value) for value in ids}
    assert len(graph["dependencies"]) == 64
    assert graph["project"]["id"] == str(project_id)
    assert graph["stages"][0]["archived"] is True
    assert graph["milestones"][0]["name"] == "验收点"
    assert "description" not in graph["tasks"][0]
    assert response.headers["X-Request-ID"] == "graph-complete"
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.integration
def test_graph_rejects_oversize_instead_of_returning_a_partial_graph(
    client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
):
    from cairn_api.projects import graph_service

    project_id, _ = seed_graph(client, database, 3)
    monkeypatch.setattr(graph_service, "MAX_GRAPH_TASKS", 2)
    response = client.get(
        f"/api/v1/projects/{project_id}/task-graph", headers={"X-Request-ID": "graph-limit"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "project_graph_too_large"
    assert response.json()["traceId"] == response.headers["X-Request-ID"] == "graph-limit"
    assert "tasks" not in response.json()


@pytest.mark.integration
def test_graph_waits_for_project_mutation_before_reading_related_rows(
    client: TestClient, database: Database
):
    project_id, ids = seed_graph(client, database, 2)
    started = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.session_factory.begin() as session:
            session.scalar(select(Project).where(Project.id == project_id).with_for_update())
            task = session.get(Task, ids[0])
            assert task is not None
            task.title = "原子更新后的任务"
            task.status = "done"

            def read_graph():
                started.set()
                return client.get(f"/api/v1/projects/{project_id}/task-graph")

            pending = pool.submit(read_graph)
            assert started.wait(2)
            # The graph cannot finish while its project's mutation lock is held.
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.2)
        response = pending.result(timeout=5)
    assert response.status_code == 200, response.text
    node = next(item for item in response.json()["tasks"] if item["id"] == str(ids[0]))
    assert (node["title"], node["status"]) == ("原子更新后的任务", "done")
    assert len(response.json()["dependencies"]) == 1


@pytest.mark.integration
def test_graph_requires_session_and_hides_other_orgs(client: TestClient, database: Database):
    from cairn_api.organizations.models import Organization

    with database.session_factory.begin() as session:
        org = Organization(slug=f"outside-{uuid4()}", name="outside")
        session.add(org)
        session.flush()
        project = Project(org_id=org.id, name="private project")
        session.add(project)
        session.flush()
        project_id = project.id
    denied = client.get(f"/api/v1/projects/{project_id}/task-graph")
    assert denied.status_code == 404
    assert "private project" not in denied.text
    client.cookies.clear()
    assert client.get(f"/api/v1/projects/{project_id}/task-graph").status_code == 401


@pytest.mark.integration
def test_read_grant_allows_graph_and_revocation_hides_it(
    client: TestClient, database: Database, api_settings: Settings
):
    from cairn_api.authorization.models import ResourceAclEntry
    from cairn_api.authorization.types import MembershipRole

    from .authorization_helpers import authenticated_client, seed_actor

    project_id, _ = seed_graph(client, database, 2)
    with database.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        org_id = project.org_id
    guest = seed_actor(database, MembershipRole.VIEWER, org_id=org_id)
    grant_id = uuid4()
    with database.session_factory.begin() as session:
        session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == project_id, ResourceAclEntry.principal_type == "org"))
        session.add(
            ResourceAclEntry(
                id=grant_id,
                org_id=org_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(guest.user_id),
                permission="read",
                granted_by_type="system",
            )
        )
    with authenticated_client(api_settings, database, guest) as reader:
        assert reader.get(f"/api/v1/projects/{project_id}/task-graph").status_code == 200
        with database.session_factory.begin() as session:
            grant = session.get(ResourceAclEntry, grant_id)
            assert grant is not None
            grant.revoked_at = datetime.now(UTC)
            grant.revoked_by_type = "system"
        denied = reader.get(f"/api/v1/projects/{project_id}/task-graph")
        assert denied.status_code == 404
        assert "完整任务图" not in denied.text
