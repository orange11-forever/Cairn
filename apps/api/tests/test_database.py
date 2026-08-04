from types import SimpleNamespace
from unittest.mock import MagicMock

from cairn_api.db.session import Database, get_db
from sqlalchemy.sql.elements import TextClause


def test_database_check_ready_executes_select_one() -> None:
    connection = MagicMock()
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = connection_context
    database = Database.__new__(Database)
    database.engine = engine

    database.check_ready()

    statement = connection.execute.call_args.args[0]
    assert isinstance(statement, TextClause)
    assert str(statement) == "SELECT 1"


def test_database_dispose_releases_engine() -> None:
    database = Database.__new__(Database)
    database.engine = MagicMock()

    database.dispose()

    database.engine.dispose.assert_called_once_with()


def test_get_db_closes_the_request_session() -> None:
    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    database = SimpleNamespace(session_factory=MagicMock(return_value=session_context))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=database)))

    dependency = get_db(request)  # type: ignore[arg-type]
    assert next(dependency) is session

    try:
        next(dependency)
    except StopIteration:
        pass
    else:
        raise AssertionError("database dependency must yield exactly one session")
    session_context.__exit__.assert_called_once_with(None, None, None)
