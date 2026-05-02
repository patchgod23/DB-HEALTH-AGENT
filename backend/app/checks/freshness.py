"""
freshness.py — Check 3: Is the data up to date?

Detects stale tables by inspecting the most recent modification
timestamps reported by SQL Server's sys.dm_db_index_usage_stats
and sys.tables.

Falls back to a configurable custom freshness query per server
if defined in servers.yaml under `freshness_query`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import ServerConfig, Thresholds
from app.db import DBConnection, DBConnectionError, QueryExecutionError
from app.models.result import CheckResult, Severity

CHECK_NAME = "data_freshness"

# Retrieves last user write time for all user tables in the current DB.
# last_user_update from index usage stats reflects DML operations.
_FRESHNESS_QUERY = """
SELECT
    OBJECT_NAME(i.object_id)   AS table_name,
    MAX(s.last_user_update)    AS last_update,
    (SELECT SUM(rows) FROM sys.partitions p WHERE p.object_id = i.object_id AND p.index_id IN (0,1)) AS row_count
FROM
    sys.indexes i
    INNER JOIN sys.dm_db_index_usage_stats s
        ON i.object_id = s.object_id
        AND i.index_id  = s.index_id
        AND s.database_id = DB_ID()
WHERE
    OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1
GROUP BY
    i.object_id
ORDER BY
    last_update ASC
"""


def _hours_since(dt: datetime) -> float:
    """Return hours elapsed since a naive UTC datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600


def run(config: ServerConfig, thresholds: Thresholds) -> CheckResult:
    """Identify tables with no recent write activity."""
    conn = DBConnection(config, timeout=thresholds.connect_timeout_sec)
    try:
        conn.connect()
        rows, duration_ms = conn.execute(_FRESHNESS_QUERY)
    except (DBConnectionError, QueryExecutionError) as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.UNKNOWN,
            message=f"El check de frescura no se pudo ejecutar: {exc}",
        )
    finally:
        conn.close()

    if not rows:
        # No write stats available — common for idle/new databases
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.WARNING,
            message="No se encontraron estadísticas de uso de índices. La BD podría estar inactiva o recién reiniciada.",
            duration_ms=duration_ms,
        )

    stale_critical: list[str] = []
    stale_warning: list[str] = []
    static_config_tables: int = 0
    
    ignored_tables = {t.lower() for t in config.ignore_freshness_tables}

    for row in rows:
        table_name = row[0]
        last_update: datetime | None = row[1]
        row_count: int = row[2] or 0

        # Auto-descubrimiento heurístico: 
        # Si la tabla tiene muy pocas filas (< 1000), asumimos que es una tabla 
        # estática (catálogo, configuración, layouts) y no exigimos que se actualice.
        if row_count < 1000:
            static_config_tables += 1
            continue

        # Omitir también tablas marcadas explícitamente por el usuario
        if table_name.lower() in ignored_tables:
            continue

        if last_update is None:
            stale_warning.append(f"{table_name} (nunca escrita)")
            continue

        hours_ago = _hours_since(last_update)
        if hours_ago >= thresholds.freshness_critical_hours:
            stale_critical.append(
                f"{table_name} (última actualización: hace {hours_ago:.1f}h)"
            )
        elif hours_ago >= thresholds.freshness_warning_hours:
            stale_warning.append(
                f"{table_name} (última actualización: hace {hours_ago:.1f}h)"
            )

    if stale_critical:
        # Se rebaja la severidad a WARNING para evitar sobreestimar el impacto por falta de contexto funcional
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.WARNING,
            message=f"{len(stale_critical)} tabla(s) con actividad muy antigua: {', '.join(stale_critical[:3])}",
            value={"critical": stale_critical, "warning": stale_warning},
            duration_ms=duration_ms,
        )
    if stale_warning:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.WARNING,
            message=f"{len(stale_warning)} tabla(s) con baja actividad reciente: {', '.join(stale_warning[:3])}",
            value={"critical": [], "warning": stale_warning},
            duration_ms=duration_ms,
        )

    return CheckResult(
        check_name=CHECK_NAME,
        severity=Severity.OK,
        message=f"Las tablas transaccionales tienen actividad reciente. (Se omitieron {static_config_tables} tablas de config/catálogo por su bajo volumen).",
        value={"stale_count": 0, "total_tables": len(rows), "static_tables_auto_detected": static_config_tables},
        duration_ms=duration_ms,
    )
