"""
connectivity.py — Check 1: Can we reach and authenticate to the database?

Validates:
  - Host is reachable
  - Credentials are valid
  - Connection completes within timeout
"""
from __future__ import annotations

from app.config import ServerConfig, Thresholds
from app.db import DBConnection, DBConnectionError
from app.models.result import CheckResult, Severity


CHECK_NAME = "connectivity"


def run(config: ServerConfig, thresholds: Thresholds) -> CheckResult:
    """Attempt to open and immediately close a connection.

    Returns OK if successful, CRITICAL otherwise.
    """
    conn = DBConnection(config, timeout=thresholds.connect_timeout_sec)
    try:
        conn.connect()
        duration = conn.connect_duration_ms
        conn.close()
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.OK,
            message=f"Conexión establecida con {config.host}:{config.port}/{config.database}",
            value=True,
            duration_ms=duration,
        )
    except DBConnectionError as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=str(exc),
            value=False,
        )
    except Exception as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=f"Error inesperado al conectar con {config.host}: {exc}",
            value=False,
        )
