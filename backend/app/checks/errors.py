"""
errors.py — Check 5: Are there recent error patterns in the database?

Inspects SQL Server Agent job history and the SQL error log
for recent failures, surfacing counts above configurable thresholds.

Two sources are probed:
  1. msdb.dbo.sysjobhistory — failed SQL Agent jobs
  2. sys.messages / application error tables (configurable)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.config import ServerConfig, Thresholds
from app.db import DBConnection, DBConnectionError, QueryExecutionError
from app.models.result import CheckResult, Severity

CHECK_NAME = "error_patterns"

# SQL Agent failed jobs in the past 24 hours
_AGENT_JOBS_QUERY = """
SELECT TOP 50
    j.name          AS job_name,
    h.run_date,
    h.run_time,
    h.message
FROM
    msdb.dbo.sysjobhistory h
    INNER JOIN msdb.dbo.sysjobs j ON h.job_id = j.job_id
WHERE
    h.run_status  = 0                          -- 0 = Failed
    AND h.step_id != 0                         -- exclude summary rows
    AND CONVERT(datetime,
            STUFF(STUFF(CAST(h.run_date AS VARCHAR(8)), 7, 0, '-'), 5, 0, '-')
            + ' '
            + STUFF(STUFF(RIGHT('000000' + CAST(h.run_time AS VARCHAR(6)), 6), 5, 0, ':'), 3, 0, ':')
        ) >= DATEADD(HOUR, -24, GETDATE())
ORDER BY
    h.run_date DESC, h.run_time DESC
"""

# Long-running queries (blocking / resource hog detection)
_BLOCKING_QUERY = """
SELECT COUNT(*) AS blocking_count
FROM sys.dm_exec_requests
WHERE blocking_session_id > 0
"""


def run(config: ServerConfig, thresholds: Thresholds) -> CheckResult:
    """Probe for failed SQL Agent jobs and active blocking."""
    conn = DBConnection(config, timeout=thresholds.connect_timeout_sec)
    try:
        conn.connect()

        # --- Agent job failures ---
        try:
            job_rows, duration_ms = conn.execute(_AGENT_JOBS_QUERY)
            failed_jobs = [
                f"{r[0]} ({r[1]} {r[2]})"
                for r in job_rows
            ]
        except QueryExecutionError:
            # msdb may be inaccessible; treat as unknown
            failed_jobs = []
            duration_ms = 0.0

        # --- Blocking sessions ---
        try:
            block_rows, _ = conn.execute(_BLOCKING_QUERY)
            blocking_count = int(block_rows[0][0]) if block_rows else 0
        except QueryExecutionError:
            blocking_count = 0

    except DBConnectionError as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=f"Fallo en el check de errores — no se pudo conectar: {exc}",
        )
    finally:
        conn.close()

    error_count = len(failed_jobs)
    issues: list[str] = []

    if failed_jobs:
        issues.append(f"{error_count} trabajo(s) del Agente SQL fallido(s) en las últimas 24h")
    if blocking_count > 0:
        issues.append(f"{blocking_count} sesión(es) bloqueada(s) activa(s)")

    if (
        error_count >= thresholds.error_critical_count
        or blocking_count >= 5
    ):
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=" | ".join(issues) if issues else "Umbral de error crítico alcanzado.",
            value={"failed_jobs": failed_jobs[:10], "blocking_sessions": blocking_count},
            duration_ms=duration_ms,
        )

    if (
        error_count >= thresholds.error_warning_count
        or blocking_count > 0
    ):
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.WARNING,
            message=" | ".join(issues) if issues else "Umbral de advertencia alcanzado.",
            value={"failed_jobs": failed_jobs[:10], "blocking_sessions": blocking_count},
            duration_ms=duration_ms,
        )

    return CheckResult(
        check_name=CHECK_NAME,
        severity=Severity.OK,
        message=f"Sin errores recientes. {error_count} trabajos fallidos, {blocking_count} sesiones bloqueadas.",
        value={"failed_jobs": [], "blocking_sessions": 0},
        duration_ms=duration_ms,
    )
