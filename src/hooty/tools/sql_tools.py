"""SQL database tools for Hooty."""

from __future__ import annotations

from typing import Optional

from agno.tools import Toolkit


class SQLToolsError(Exception):
    """Raised when SQLTools creation fails (e.g. missing DB driver)."""


def dispose_sql_tools(agent: object) -> None:
    """Dispose SQLAlchemy engine held by any SQLTools in the agent's tools."""
    for toolkit in getattr(agent, "tools", []) or []:
        engine = getattr(toolkit, "db_engine", None)
        if engine is not None:
            engine.dispose()


def create_sql_tools(db_url: str) -> Optional[Toolkit]:
    """Create SQLTools for a database connection URL.

    Raises ``SQLToolsError`` when the DB driver is missing or the
    connection URL is invalid.
    """
    try:
        from agno.tools.sql import SQLTools
    except ImportError:
        return None

    try:
        return SQLTools(db_url=db_url)
    except ModuleNotFoundError as e:
        raise SQLToolsError(
            f"DB driver not found: {e.name}\n"
            f"  pip install {e.name}"
        ) from e
    except Exception as e:
        raise SQLToolsError(f"DB connection failed: {e}") from e
