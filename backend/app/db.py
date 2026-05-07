"""
db.py — Database connection manager for db-health-agent.

Provides a context-managed SQL connection with timing,
error handling, and support for pyodbc (SQL Server) and
SQLAlchemy-backed engines for multi-dialect support.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator, Optional

from loguru import logger

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False

from app.config import ServerConfig


class DBConnectionError(Exception):
    """Raised when a database connection cannot be established."""


class QueryExecutionError(Exception):
    """Raised when a query fails during execution."""


class DBConnection:
    """Manages a single database connection lifecycle."""

    def __init__(self, config: ServerConfig, timeout: int = 5):
        self.config = config
        self.timeout = timeout
        self._conn: Optional[Any] = None
        self.connect_duration_ms: float = 0.0

    def connect(self) -> None:
        """Open a database connection and record latency."""
        if not PYODBC_AVAILABLE:
            raise DBConnectionError(
                "pyodbc is not installed. Run: pip install pyodbc"
            )

        conn_str = (
            f"DRIVER={{{self.config.driver}}};"
            f"SERVER={self.config.host},{self.config.port};"
            f"DATABASE={self.config.database};"
            f"UID={self.config.username};"
            f"PWD={self.config.password};"
            f"Connect Timeout={self.timeout};"
            f"TrustServerCertificate=yes;"
        )

        start = time.perf_counter()
        try:
            self._conn = pyodbc.connect(conn_str, timeout=self.timeout, autocommit=True)
        except pyodbc.Error as exc:
            raise DBConnectionError(
                f"Cannot connect to [{self.config.id}] {self.config.host}: {exc}"
            ) from exc
        finally:
            self.connect_duration_ms = (time.perf_counter() - start) * 1000

        logger.debug(
            f"[{self.config.id}] Connected in {self.connect_duration_ms:.1f}ms"
        )

    def execute(self, sql: str, params: tuple = ()) -> tuple[list[Any], float]:
        """Execute a query and return (rows, duration_ms)."""
        if self._conn is None:
            raise DBConnectionError("Not connected. Call connect() first.")

        start = time.perf_counter()
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            
            rows = []
            try:
                # Solo intentamos fetchall si hay resultados pendientes (evita error en DELETE/DBCC)
                if cursor.description:
                    rows = cursor.fetchall()
            except pyodbc.Error as e:
                # Si el error es "No results. (0) (SQLFetch)", lo ignoramos para comandos DML/DDL
                if "No results" not in str(e):
                    raise
            
            duration_ms = (time.perf_counter() - start) * 1000
            return rows, duration_ms
        except Exception as exc:
            raise QueryExecutionError(
                f"Query failed on [{self.config.id}]: {exc}"
            ) from exc

    def close(self) -> None:
        """Safely close the connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

    def __enter__(self) -> "DBConnection":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()


@contextmanager
def get_connection(
    config: ServerConfig, timeout: int = 5
) -> Generator[DBConnection, None, None]:
    """Context manager that yields an open DBConnection."""
    conn = DBConnection(config, timeout=timeout)
    try:
        conn.connect()
        yield conn
    finally:
        conn.close()
