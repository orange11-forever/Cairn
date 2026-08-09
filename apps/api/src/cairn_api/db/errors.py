from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
    PendingRollbackError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

DATABASE_UNAVAILABLE_ERRORS = (
    DisconnectionError,
    InterfaceError,
    OperationalError,
    PendingRollbackError,
    SQLAlchemyTimeoutError,
)

__all__ = ["DATABASE_UNAVAILABLE_ERRORS"]
