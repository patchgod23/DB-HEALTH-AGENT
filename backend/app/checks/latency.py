"""
latency.py — Check 2: How fast does the database respond?

Validates:
  - Query round-trip time for a trivial SELECT
  - Compares against WARNING / CRITICAL thresholds
"""
from __future__ import annotations

from app.config import ServerConfig, Thresholds
from app.db import DBConnection, DBConnectionError, QueryExecutionError
from app.models.result import CheckResult, Severity

CHECK_NAME = "query_latency"

# Minimal query — no table scan, purely tests engine responsiveness
_PROBE_QUERY = "SELECT 1 AS probe"


def run(config: ServerConfig, thresholds: Thresholds) -> CheckResult:
    """Run a trivial query and classify round-trip latency."""
    conn = DBConnection(config, timeout=thresholds.connect_timeout_sec)
    try:
        conn.connect()
        _, duration_ms = conn.execute(_PROBE_QUERY)
    except (DBConnectionError, QueryExecutionError) as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=f"Fallo en el check de latencia: {exc}",
        )
    finally:
        conn.close()

    if duration_ms >= thresholds.latency_critical_ms:
        severity = Severity.CRITICAL
        msg = (
            f"Tiempo de respuesta CRÍTICO: {duration_ms:.1f}ms "
            f"(umbral: {thresholds.latency_critical_ms}ms)"
        )
    elif duration_ms >= thresholds.latency_warning_ms:
        severity = Severity.WARNING
        msg = (
            f"Tiempo de respuesta elevado: {duration_ms:.1f}ms "
            f"(umbral: {thresholds.latency_warning_ms}ms)"
        )
    else:
        severity = Severity.OK
        msg = f"Tiempo de respuesta normal: {duration_ms:.1f}ms"

    return CheckResult(
        check_name=CHECK_NAME,
        severity=severity,
        message=msg,
        value=round(duration_ms, 2),
        threshold={
            "warning_ms": thresholds.latency_warning_ms,
            "critical_ms": thresholds.latency_critical_ms,
        },
        duration_ms=duration_ms,
    )
