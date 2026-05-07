"""
db_size.py — Check 6: Measuring database and log size.
"""
from __future__ import annotations
from app.config import ServerConfig, Thresholds
from app.db import DBConnection, DBConnectionError, QueryExecutionError
from app.models.result import CheckResult, Severity

CHECK_NAME = "database_size"

# Consulta mejorada para separar DATA de LOG
_SIZE_QUERY = """
SELECT 
    type_desc,
    size * 8.0 / 1024 as size_mb
FROM sys.master_files 
WHERE database_id = DB_ID(?)
"""

def run(config: ServerConfig, thresholds: Thresholds) -> CheckResult:
    """Measure DB and Log size."""
    conn = DBConnection(config, timeout=thresholds.connect_timeout_sec)
    try:
        conn.connect()
        rows, duration_ms = conn.execute(_SIZE_QUERY, (config.database,))
        
        data_mb = 0.0
        log_mb = 0.0
        
        for row in rows:
            if row[0] == 'ROWS':
                data_mb += float(row[1])
            elif row[0] == 'LOG':
                log_mb += float(row[1])
        
        total_gb = (data_mb + log_mb) / 1024
        
        msg = f"Tamaño Total: {total_gb:.2f} GB (Data: {data_mb/1024:.2f}GB, Log: {log_mb/1024:.2f}GB)"
        
        # Guardamos los valores detallados en el 'value' para que la IA los vea
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.OK,
            message=msg,
            value={
                "total_gb": total_gb,
                "data_gb": data_mb / 1024,
                "log_gb": log_mb / 1024
            },
            duration_ms=duration_ms
        )
    except (DBConnectionError, QueryExecutionError) as exc:
        return CheckResult(
            check_name=CHECK_NAME,
            severity=Severity.CRITICAL,
            message=f"Fallo al medir el tamaño de la bd: {exc}",
        )
    finally:
        conn.close()
