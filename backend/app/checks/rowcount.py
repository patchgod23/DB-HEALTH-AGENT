"""
rowcount.py — Check 4: Are row volumes within expected ranges?

Compares current row counts against a baseline stored from the
previous run. Detects abnormal drops that may indicate failed
ETL loads, truncations, or data loss.

Baseline is persisted in logs/rowcount_baseline.json.
"""
from __future__ import annotations

import os

from app.config import ServerConfig, Thresholds
from app.db import DBConnection, DBConnectionError, QueryExecutionError
from app.models.result import CheckResult, Severity
from app.storage.state import get_rowcount_baselines, save_rowcounts

CHECK_NAME = "row_count"

# Old baseline file logic removed, using SQLite from app.storage.state


# Fetch row counts for all user tables (uses fast partition stats)
_ROWCOUNT_QUERY = """
SELECT
    t.name                                        AS table_name,
    SUM(p.rows)                                   AS row_count
FROM
    sys.tables t
    INNER JOIN sys.partitions p
        ON t.object_id = p.object_id
        AND p.index_id IN (0, 1)      -- heap or clustered index
WHERE
    t.is_ms_shipped = 0
GROUP BY
    t.name
ORDER BY
    row_count DESC
"""

def run(config: ServerConfig, thresholds: Thresholds) -> CheckResult:
    """Compare current row counts to baseline and detect drops."""
    conn = DBConnection(config, timeout=thresholds.connect_timeout_sec)
    try:
        conn.connect()
        rows, duration_ms = conn.execute(_ROWCOUNT_QUERY)
    except (DBConnectionError, QueryExecutionError) as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=f"Fallo en el check de conteo de filas: {exc}",
        )
    finally:
        conn.close()

    current: dict[str, int] = {row[0]: int(row[1]) for row in rows}
    
    # Empty tables — immediate warning
    empty_tables = [t for t, c in current.items() if c == 0]

    critical_drops: list[str] = []
    warning_drops: list[str] = []

    is_first_run = True

    for table, curr_count in current.items():
        baselines = get_rowcount_baselines(config.id, table)
        prev_count = baselines["t_prev"]
        
        if prev_count is not None:
            is_first_run = False
            
        if prev_count is None or prev_count == 0:
            continue
            
        drop_pct_prev = ((prev_count - curr_count) / prev_count) * 100
        
        # Slow bleed calculation
        t_1h = baselines["t_1h"]
        drop_pct_1h = ((t_1h - curr_count) / t_1h) * 100 if t_1h else 0
        
        t_24h = baselines["t_24h"]
        drop_pct_24h = ((t_24h - curr_count) / t_24h) * 100 if t_24h else 0

        # Obtener perfil de la tabla (por defecto asumimos append_only)
        table_type = config.table_profiles.get(table, "append_only").lower()

        if table_type == "rolling":
            if curr_count == 0:
                critical_drops.append(f"{table} (rolling truncada a 0: {prev_count:,} → 0)")
            elif drop_pct_prev >= 80:
                warning_drops.append(f"{table} (rolling purge masivo >80%: {prev_count:,} → {curr_count:,})")
            elif drop_pct_prev >= 50:
                warning_drops.append(f"{table} (rolling purge >50%: {prev_count:,} → {curr_count:,})")
            
        elif table_type == "static":
            if curr_count == 0:
                critical_drops.append(f"{table} (static borrada: {prev_count:,} → 0)")
            elif drop_pct_prev >= 10:
                warning_drops.append(f"{table} (static reducida: {prev_count:,} → {curr_count:,})")
                
        elif table_type == "derived_state":
            if curr_count == 0:
                warning_drops.append(f"{table} (derived vacía, posible recálculo en curso: {prev_count:,} → 0)")
            elif drop_pct_prev >= 95:
                warning_drops.append(f"{table} (derived cambio de set >95%: {prev_count:,} → {curr_count:,})")
                
        else:
            # append_only o sin clasificar (reglas tradicionales)
            # 1. Shock detection (T-1)
            if drop_pct_prev >= thresholds.rowcount_critical_drop_pct:
                critical_drops.append(f"{table} ({prev_count:,} → {curr_count:,}, -{drop_pct_prev:.1f}%)")
            elif drop_pct_prev >= thresholds.rowcount_warning_drop_pct:
                warning_drops.append(f"{table} ({prev_count:,} → {curr_count:,}, -{drop_pct_prev:.1f}%)")
                
            # 2. Slow Bleed detection (1h y 24h)
            elif drop_pct_1h >= thresholds.rowcount_critical_drop_pct:
                critical_drops.append(f"{table} (Slow bleed 1h: {t_1h:,} → {curr_count:,}, -{drop_pct_1h:.1f}%)")
            elif drop_pct_24h >= thresholds.rowcount_critical_drop_pct:
                critical_drops.append(f"{table} (Slow bleed 24h: {t_24h:,} → {curr_count:,}, -{drop_pct_24h:.1f}%)")
            elif drop_pct_24h >= thresholds.rowcount_warning_drop_pct:
                warning_drops.append(f"{table} (Slow bleed 24h: {t_24h:,} → {curr_count:,}, -{drop_pct_24h:.1f}%)")

    if is_first_run:
        save_rowcounts(config.id, current)
        msg = f"Línea base establecida (SQLite) para {len(current)} tablas."
        if empty_tables:
            msg += f" {len(empty_tables)} tabla(s) vacías."
            return CheckResult(
                check_name=CHECK_NAME, severity=Severity.WARNING, message=msg,
                value={"tables": len(current), "empty": empty_tables}, duration_ms=duration_ms,
            )
        return CheckResult(
            check_name=CHECK_NAME, severity=Severity.OK, message=msg,
            value={"tables": len(current)}, duration_ms=duration_ms,
        )

    # Update baseline after comparison
    save_rowcounts(config.id, current)

    if critical_drops:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=f"Se detectaron caídas CRÍTICAS en el conteo de filas: {'; '.join(critical_drops[:3])}",
            value={"critical": critical_drops, "warning": warning_drops, "empty": empty_tables},
            duration_ms=duration_ms,
        )
    if warning_drops or empty_tables:
        parts = []
        if warning_drops:
            parts.append(f"Caídas de filas: {'; '.join(warning_drops[:3])}")
        if empty_tables:
            parts.append(f"Tablas vacías: {', '.join(empty_tables[:5])}")
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.WARNING,
            message=" | ".join(parts),
            value={"critical": [], "warning": warning_drops, "empty": empty_tables},
            duration_ms=duration_ms,
        )

    return CheckResult(
        check_name=CHECK_NAME,
        severity=Severity.OK,
        message=f"Conteos de filas estables en {len(current)} tablas.",
        value={"tables": len(current)},
        duration_ms=duration_ms,
    )
