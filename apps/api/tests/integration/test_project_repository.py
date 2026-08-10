from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.organizations.models import Organization
from cairn_api.projects import repository
from cairn_api.projects.models import Project
from sqlalchemy import Connection, MetaData, Table, insert, text
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_project_access_filter_is_applied_before_cursor_pagination(
    migrated_connection: Connection,
) -> None:
    """Break caught: filtering after LIMIT omits later authorized rows and leaks a cursor."""
    org_id = uuid4()
    user_id = uuid4()
    base = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
    projects = [
        Project(
            id=uuid4(),
            org_id=org_id,
            name=name,
            created_at=base + timedelta(seconds=index),
            updated_at=base + timedelta(seconds=index),
        )
        for index, name in enumerate(("Visible A", "Hidden B", "Visible C"))
    ]
    with Session(bind=migrated_connection) as session:
        session.add(Organization(id=org_id, slug=f"filter-{org_id}", name="Filter org"))
        session.add_all(projects)
        session.flush()
        session.add_all(
            [
                ResourceAclEntry(
                    org_id=org_id,
                    resource_type="project",
                    resource_id=project.id,
                    principal_type="user",
                    principal_id=str(user_id),
                    permission="read",
                    granted_by_type="system",
                )
                for project in (projects[0], projects[2])
            ]
        )
        session.flush()
        access_filter = Project.id.in_((projects[0].id, projects[2].id))
        page, cursor = repository.list_projects(
            session,
            org_id=org_id,
            access_filter=access_filter,
            cursor=None,
            limit=2,
        )

    assert [project.id for project in page] == [projects[0].id, projects[2].id]
    assert cursor is None


@pytest.mark.integration
def test_dependency_reachability_deduplicates_layered_diamond_nodes(
    migrated_connection: Connection,
) -> None:
    """Break caught: recursive reachability expands one row per path and times out."""
    metadata = MetaData()
    organizations = Table("organizations", metadata, autoload_with=migrated_connection)
    projects = Table("projects", metadata, autoload_with=migrated_connection)
    tasks = Table("tasks", metadata, autoload_with=migrated_connection)
    dependencies = Table("task_dependencies", metadata, autoload_with=migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000111")
    project_id = UUID("00000000-0000-4000-8000-000000000211")
    start_task_id = UUID("00000000-0000-4000-8000-000000000311")
    missing_task_id = UUID("00000000-0000-4000-8000-000000000399")
    layers = [
        [UUID(int=10_000 + layer * 2 + offset) for offset in range(2)]
        for layer in range(30)
    ]

    migrated_connection.execute(
        insert(organizations),
        {"id": org_id, "slug": "repository-diamond", "name": "Repository diamond"},
    )
    migrated_connection.execute(
        insert(projects),
        {"id": project_id, "org_id": org_id, "name": "Layered diamond"},
    )
    migrated_connection.execute(
        insert(tasks),
        [
            {
                "id": task_id,
                "org_id": org_id,
                "project_id": project_id,
                "title": f"Layered task {index}",
            }
            for index, task_id in enumerate(
                [start_task_id, *(task_id for layer in layers for task_id in layer)]
            )
        ],
    )
    edge_pairs = [
        (start_task_id, successor_id)
        for successor_id in layers[0]
    ] + [
        (predecessor_id, successor_id)
        for predecessor_layer, successor_layer in pairwise(layers)
        for predecessor_id in predecessor_layer
        for successor_id in successor_layer
    ]
    migrated_connection.execute(
        insert(dependencies),
        [
            {
                "id": UUID(int=20_000 + index),
                "org_id": org_id,
                "project_id": project_id,
                "predecessor_task_id": predecessor_id,
                "successor_task_id": successor_id,
            }
            for index, (predecessor_id, successor_id) in enumerate(edge_pairs)
        ],
    )
    migrated_connection.execute(text("SET LOCAL statement_timeout = '250ms'"))

    with Session(bind=migrated_connection) as session:
        assert repository.dependency_path_exists(
            session,
            org_id=org_id,
            start_task_id=start_task_id,
            target_task_id=missing_task_id,
        ) is False
