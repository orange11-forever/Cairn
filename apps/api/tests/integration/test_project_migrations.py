from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, MetaData, Table, create_engine, insert, inspect, select
from sqlalchemy.exc import IntegrityError

PROJECT_TABLES = {
    "projects",
    "project_stages",
    "milestones",
    "tasks",
    "task_dependencies",
    "outbox_events",
}


@pytest.mark.integration
def test_project_migration_creates_all_tenant_tables(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    assert set(inspector.get_table_names()) >= PROJECT_TABLES
    for table_name in PROJECT_TABLES:
        assert "org_id" in {
            column["name"] for column in inspector.get_columns(table_name)
        }
    assert "acceptance_criteria" in {
        column["name"] for column in inspector.get_columns("tasks")
    }
    task_indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes("tasks")
    }
    assert task_indexes["ix_tasks_org_id_project_id_created_at_id"] == [
        "org_id",
        "project_id",
        "created_at",
        "id",
    ]


@pytest.mark.integration
def test_task_acceptance_criteria_is_stored_independently_from_description(
    migrated_connection: Connection,
) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000104")
    project_id = UUID("00000000-0000-4000-8000-000000000204")
    task_id = UUID("00000000-0000-4000-8000-000000000304")
    _insert_project_graph(migrated_connection, tables, org_id, project_id)

    migrated_connection.execute(
        insert(tables["tasks"]),
        {
            "id": task_id,
            "org_id": org_id,
            "project_id": project_id,
            "title": "Contract test",
            "description": "Why this task exists",
            "acceptance_criteria": "The observable completion contract",
        },
    )

    row = migrated_connection.execute(
        select(
            tables["tasks"].c.description,
            tables["tasks"].c.acceptance_criteria,
        ).where(tables["tasks"].c.id == task_id)
    ).one()
    assert row.description == "Why this task exists"
    assert row.acceptance_criteria == "The observable completion contract"


@pytest.mark.integration
def test_task_dependency_rejects_self_edge(migrated_connection: Connection) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000101")
    project_id = UUID("00000000-0000-4000-8000-000000000201")
    task_id = UUID("00000000-0000-4000-8000-000000000301")
    _insert_project_graph(migrated_connection, tables, org_id, project_id, task_id)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["task_dependencies"]),
            _dependency_values(
                tables["task_dependencies"],
                dependency_id=UUID("00000000-0000-4000-8000-000000000401"),
                org_id=org_id,
                project_id=project_id,
                predecessor_task_id=task_id,
                successor_task_id=task_id,
            ),
        )


@pytest.mark.integration
def test_task_dependency_rejects_duplicate_edge(migrated_connection: Connection) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000102")
    project_id = UUID("00000000-0000-4000-8000-000000000202")
    predecessor_id = UUID("00000000-0000-4000-8000-000000000302")
    successor_id = UUID("00000000-0000-4000-8000-000000000303")
    _insert_project_graph(
        migrated_connection,
        tables,
        org_id,
        project_id,
        predecessor_id,
        successor_id,
    )

    edge = {
        "org_id": org_id,
        "project_id": project_id,
        "predecessor_task_id": predecessor_id,
        "successor_task_id": successor_id,
    }
    migrated_connection.execute(
        insert(tables["task_dependencies"]),
        {"id": UUID("00000000-0000-4000-8000-000000000402"), **edge},
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["task_dependencies"]),
            {"id": UUID("00000000-0000-4000-8000-000000000403"), **edge},
        )


@pytest.mark.integration
def test_task_stage_rejects_cross_project_reference(
    migrated_connection: Connection,
) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000105")
    project_a_id = UUID("00000000-0000-4000-8000-000000000205")
    project_b_id = UUID("00000000-0000-4000-8000-000000000206")
    stage_a_id = UUID("00000000-0000-4000-8000-000000000505")
    stage_b_id = UUID("00000000-0000-4000-8000-000000000506")
    _insert_two_projects(migrated_connection, tables, org_id, project_a_id, project_b_id)
    migrated_connection.execute(
        insert(tables["project_stages"]),
        [
            {
                "id": stage_a_id,
                "org_id": org_id,
                "project_id": project_a_id,
                "name": "Project A stage",
            },
            {
                "id": stage_b_id,
                "org_id": org_id,
                "project_id": project_b_id,
                "name": "Project B stage",
            },
        ],
    )
    migrated_connection.execute(
        insert(tables["tasks"]),
        {
            "id": UUID("00000000-0000-4000-8000-000000000305"),
            "org_id": org_id,
            "project_id": project_a_id,
            "stage_id": stage_a_id,
            "title": "Same-project stage",
        },
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["tasks"]),
            {
                "id": UUID("00000000-0000-4000-8000-000000000306"),
                "org_id": org_id,
                "project_id": project_a_id,
                "stage_id": stage_b_id,
                "title": "Cross-project stage",
            },
        )


@pytest.mark.integration
def test_task_milestone_rejects_cross_project_reference(
    migrated_connection: Connection,
) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000106")
    project_a_id = UUID("00000000-0000-4000-8000-000000000207")
    project_b_id = UUID("00000000-0000-4000-8000-000000000208")
    milestone_a_id = UUID("00000000-0000-4000-8000-000000000605")
    milestone_b_id = UUID("00000000-0000-4000-8000-000000000606")
    _insert_two_projects(migrated_connection, tables, org_id, project_a_id, project_b_id)
    migrated_connection.execute(
        insert(tables["milestones"]),
        [
            {
                "id": milestone_a_id,
                "org_id": org_id,
                "project_id": project_a_id,
                "name": "Project A milestone",
            },
            {
                "id": milestone_b_id,
                "org_id": org_id,
                "project_id": project_b_id,
                "name": "Project B milestone",
            },
        ],
    )
    migrated_connection.execute(
        insert(tables["tasks"]),
        {
            "id": UUID("00000000-0000-4000-8000-000000000307"),
            "org_id": org_id,
            "project_id": project_a_id,
            "milestone_id": milestone_a_id,
            "title": "Same-project milestone",
        },
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["tasks"]),
            {
                "id": UUID("00000000-0000-4000-8000-000000000308"),
                "org_id": org_id,
                "project_id": project_a_id,
                "milestone_id": milestone_b_id,
                "title": "Cross-project milestone",
            },
        )


@pytest.mark.integration
def test_task_parent_rejects_cross_project_reference(
    migrated_connection: Connection,
) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000107")
    project_a_id = UUID("00000000-0000-4000-8000-000000000209")
    project_b_id = UUID("00000000-0000-4000-8000-000000000210")
    parent_a_id = UUID("00000000-0000-4000-8000-000000000309")
    parent_b_id = UUID("00000000-0000-4000-8000-000000000310")
    _insert_two_projects(migrated_connection, tables, org_id, project_a_id, project_b_id)
    migrated_connection.execute(
        insert(tables["tasks"]),
        [
            {
                "id": parent_a_id,
                "org_id": org_id,
                "project_id": project_a_id,
                "title": "Project A parent",
            },
            {
                "id": parent_b_id,
                "org_id": org_id,
                "project_id": project_b_id,
                "title": "Project B parent",
            },
        ],
    )
    migrated_connection.execute(
        insert(tables["tasks"]),
        {
            "id": UUID("00000000-0000-4000-8000-000000000311"),
            "org_id": org_id,
            "project_id": project_a_id,
            "parent_task_id": parent_a_id,
            "title": "Same-project child",
        },
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["tasks"]),
            {
                "id": UUID("00000000-0000-4000-8000-000000000312"),
                "org_id": org_id,
                "project_id": project_a_id,
                "parent_task_id": parent_b_id,
                "title": "Cross-project child",
            },
        )


@pytest.mark.integration
def test_task_dependency_rejects_cross_project_edge(
    migrated_connection: Connection,
) -> None:
    tables = _project_graph_tables(migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000000108")
    project_a_id = UUID("00000000-0000-4000-8000-000000000211")
    project_b_id = UUID("00000000-0000-4000-8000-000000000212")
    predecessor_a_id = UUID("00000000-0000-4000-8000-000000000313")
    successor_a_id = UUID("00000000-0000-4000-8000-000000000314")
    successor_b_id = UUID("00000000-0000-4000-8000-000000000315")
    _insert_two_projects(migrated_connection, tables, org_id, project_a_id, project_b_id)
    migrated_connection.execute(
        insert(tables["tasks"]),
        [
            {
                "id": predecessor_a_id,
                "org_id": org_id,
                "project_id": project_a_id,
                "title": "Project A predecessor",
            },
            {
                "id": successor_a_id,
                "org_id": org_id,
                "project_id": project_a_id,
                "title": "Project A successor",
            },
            {
                "id": successor_b_id,
                "org_id": org_id,
                "project_id": project_b_id,
                "title": "Project B successor",
            },
        ],
    )
    migrated_connection.execute(
        insert(tables["task_dependencies"]),
        _dependency_values(
            tables["task_dependencies"],
            dependency_id=UUID("00000000-0000-4000-8000-000000000405"),
            org_id=org_id,
            project_id=project_a_id,
            predecessor_task_id=predecessor_a_id,
            successor_task_id=successor_a_id,
        ),
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["task_dependencies"]),
            _dependency_values(
                tables["task_dependencies"],
                dependency_id=UUID("00000000-0000-4000-8000-000000000406"),
                org_id=org_id,
                project_id=project_a_id,
                predecessor_task_id=predecessor_a_id,
                successor_task_id=successor_b_id,
            ),
        )


@pytest.mark.integration
def test_project_migration_downgrade_removes_tables_and_restores_head(
    test_database_url: str,
) -> None:
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    engine = create_engine(test_database_url, pool_pre_ping=True)

    try:
        command.upgrade(config, "head")
        assert "ix_tasks_org_id_project_id_created_at_id" in {
            index["name"] for index in inspect(engine).get_indexes("tasks")
        }
        try:
            command.downgrade(config, "0002_auth_rate_limits")
            assert PROJECT_TABLES.isdisjoint(inspect(engine).get_table_names())
        finally:
            command.upgrade(config, "head")

        assert set(inspect(engine).get_table_names()) >= PROJECT_TABLES
        restored_indexes = {
            index["name"]: index["column_names"]
            for index in inspect(engine).get_indexes("tasks")
        }
        assert restored_indexes["ix_tasks_org_id_project_id_created_at_id"] == [
            "org_id",
            "project_id",
            "created_at",
            "id",
        ]
    finally:
        engine.dispose()


def _project_graph_tables(connection: Connection) -> dict[str, Table]:
    metadata = MetaData()
    return {
        name: Table(name, metadata, autoload_with=connection)
        for name in (
            "organizations",
            "projects",
            "project_stages",
            "milestones",
            "tasks",
            "task_dependencies",
        )
    }


def _insert_two_projects(
    connection: Connection,
    tables: dict[str, Table],
    org_id: UUID,
    project_a_id: UUID,
    project_b_id: UUID,
) -> None:
    connection.execute(
        insert(tables["organizations"]),
        {"id": org_id, "slug": f"project-{org_id.int}", "name": "Project test"},
    )
    connection.execute(
        insert(tables["projects"]),
        [
            {"id": project_a_id, "org_id": org_id, "name": "Project A"},
            {"id": project_b_id, "org_id": org_id, "name": "Project B"},
        ],
    )


def _dependency_values(
    dependency_table: Table,
    *,
    dependency_id: UUID,
    org_id: UUID,
    project_id: UUID,
    predecessor_task_id: UUID,
    successor_task_id: UUID,
) -> dict[str, UUID]:
    values = {
        "id": dependency_id,
        "org_id": org_id,
        "predecessor_task_id": predecessor_task_id,
        "successor_task_id": successor_task_id,
    }
    if "project_id" in dependency_table.c:
        values["project_id"] = project_id
    return values


def _insert_project_graph(
    connection: Connection,
    tables: dict[str, Table],
    org_id: UUID,
    project_id: UUID,
    *task_ids: UUID,
) -> None:
    connection.execute(
        insert(tables["organizations"]),
        {"id": org_id, "slug": f"project-{org_id.int}", "name": "Project test"},
    )
    connection.execute(
        insert(tables["projects"]),
        {"id": project_id, "org_id": org_id, "name": "Test project"},
    )
    if task_ids:
        connection.execute(
            insert(tables["tasks"]),
            [
                {
                    "id": task_id,
                    "org_id": org_id,
                    "project_id": project_id,
                    "title": f"Task {index}",
                }
                for index, task_id in enumerate(task_ids)
            ],
        )
