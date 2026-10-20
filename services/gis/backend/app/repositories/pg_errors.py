"""Reading PostgreSQL's answer out of a driver error.

asyncpg wraps the server's error in an exception that SQLAlchemy wraps again. The details that decide how
a repository reports a failure - the SQLSTATE, the constraint that was violated, the message a trigger
raised - live on the innermost exception, so they are read here once instead of in every repository.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy.exc import DBAPIError

CHECK_VIOLATION: Final = "23514"
UNIQUE_VIOLATION: Final = "23505"
FOREIGN_KEY_VIOLATION: Final = "23503"
EXCLUSION_VIOLATION: Final = "23P01"
# Triggers in this schema raise data exceptions with this SQLSTATE for geometry they refuse.
INVALID_PARAMETER_VALUE: Final = "22023"


def driver_error(error: DBAPIError) -> Any:
    return error.orig.__cause__ if error.orig is not None else None


def sqlstate(error: DBAPIError) -> str | None:
    cause = driver_error(error)
    code = getattr(cause, "sqlstate", None) or getattr(error.orig, "sqlstate", None)
    return code if isinstance(code, str) else None


def violated_constraint(error: DBAPIError) -> str | None:
    name = getattr(driver_error(error), "constraint_name", None)
    return name if isinstance(name, str) else None


def server_message(error: DBAPIError) -> str:
    cause = driver_error(error)
    return str(getattr(cause, "message", "") or error.orig or error)
