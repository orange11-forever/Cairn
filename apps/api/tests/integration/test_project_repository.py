from itertools import pairwise
from uuid import UUID

import pytest
from cairn_api.projects import repository
from sqlalchemy import Connection, MetaData, Table, insert, text
from sqlalchemy.orm import Session


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
