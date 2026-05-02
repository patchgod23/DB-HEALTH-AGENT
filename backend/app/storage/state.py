"""
state.py — SQLite-based local state management for db-health-agent.

Handles:
1. Time-series storage for row counts (to detect slow bleed).
2. LLM response caching (to prevent token burn).
"""
import sqlite3
import os
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Any

from loguru import logger

DB_PATH = "logs/state.db"

def init_db():
    """Initialize the SQLite database schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for row counts time-series
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rowcount_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rowcount_server_table ON rowcount_history(server_id, table_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rowcount_timestamp ON rowcount_history(timestamp)")
    
    # Table for LLM caching
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            server_id TEXT PRIMARY KEY,
            context_hash TEXT NOT NULL,
            narrative TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

def save_rowcounts(server_id: str, current_counts: dict[str, int]):
    """Save current row counts to SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    data = [
        (server_id, table, count, now)
        for table, count in current_counts.items()
    ]
    
    cursor.executemany("""
        INSERT INTO rowcount_history (server_id, table_name, row_count, timestamp)
        VALUES (?, ?, ?, ?)
    """, data)
    
    # Cleanup data older than 7 days
    seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("DELETE FROM rowcount_history WHERE timestamp < ?", (seven_days_ago,))
    
    conn.commit()
    conn.close()

def get_rowcount_baselines(server_id: str, table_name: str) -> dict[str, int]:
    """
    Fetch baseline row counts for specific time windows.
    Returns dict with keys: 't_prev', 't_1h', 't_24h'
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    now = datetime.utcnow()
    t_1h_ago = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    t_24h_ago = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    
    baselines = {"t_prev": None, "t_1h": None, "t_24h": None}
    
    # Get immediate previous run (T-1)
    cursor.execute("""
        SELECT row_count FROM rowcount_history 
        WHERE server_id = ? AND table_name = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (server_id, table_name))
    row = cursor.fetchone()
    if row is not None:
        baselines["t_prev"] = row[0]
        
    # Get count closest to 1 hour ago (T-1h)
    cursor.execute("""
        SELECT row_count FROM rowcount_history 
        WHERE server_id = ? AND table_name = ? AND timestamp <= ?
        ORDER BY timestamp DESC LIMIT 1
    """, (server_id, table_name, t_1h_ago))
    row = cursor.fetchone()
    if row is not None:
        baselines["t_1h"] = row[0]
        
    # Get count closest to 24 hours ago (T-24h)
    cursor.execute("""
        SELECT row_count FROM rowcount_history 
        WHERE server_id = ? AND table_name = ? AND timestamp <= ?
        ORDER BY timestamp DESC LIMIT 1
    """, (server_id, table_name, t_24h_ago))
    row = cursor.fetchone()
    if row is not None:
        baselines["t_24h"] = row[0]
        
    conn.close()
    return baselines

def _extract_entities(check: Any) -> list[str]:
    """Extrae nombres de tablas limpias (sin números que muten) de los valores del check."""
    entities = set()
    if not isinstance(check.value, dict):
        return []
        
    if check.check_name == "row_count":
        for key in ["critical", "warning", "empty"]:
            for item in check.value.get(key, []):
                # Formato: "NombreTabla (100 -> 0)" -> "NombreTabla"
                table = item.split(" ")[0] if " " in item else item
                entities.add(table)
                
    elif check.check_name == "data_freshness":
        for key in ["critical", "warning"]:
            for item in check.value.get(key, []):
                # Formato: "NombreTabla (última..." -> "NombreTabla"
                table = item.split(" ")[0] if " " in item else item
                entities.add(table)
                
    elif check.check_name == "error_patterns":
        # Formato: dict con 'failed_jobs', 'blocked_sessions'
        if check.value.get("failed_jobs"):
            entities.add("jobs_fallidos")
        if check.value.get("blocked_sessions"):
            entities.add("sesiones_bloqueadas")
            
    return sorted(list(entities))


def get_cached_llm_narrative(server_id: str, diagnosis: Any) -> Optional[str]:
    """Check if the severity state vector + incident fingerprint matches the last LLM response."""
    # Fingerprint: Severidad + Entidades Afectadas (sin métricas exactas que muten)
    fingerprint = {
        "status": diagnosis.overall_severity.value,
        "checks": {
            c.check_name: {
                "severity": c.severity.value,
                "entities": _extract_entities(c)
            } for c in diagnosis.checks
        }
    }
    state_str = json.dumps(fingerprint, sort_keys=True)
    current_hash = hashlib.sha256(state_str.encode('utf-8')).hexdigest()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT context_hash, narrative FROM llm_cache WHERE server_id = ?
    """, (server_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == current_hash:
        logger.debug(f"[{server_id}] LLM Context Hash match (Estado estable). Retornando narrativa cacheada.")
        return row[1]
    
    return None

def save_llm_narrative(server_id: str, diagnosis: Any, narrative: str):
    """Save the new incident fingerprint hash and narrative to SQLite."""
    fingerprint = {
        "status": diagnosis.overall_severity.value,
        "checks": {
            c.check_name: {
                "severity": c.severity.value,
                "entities": _extract_entities(c)
            } for c in diagnosis.checks
        }
    }
    state_str = json.dumps(fingerprint, sort_keys=True)
    current_hash = hashlib.sha256(state_str.encode('utf-8')).hexdigest()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO llm_cache (server_id, context_hash, narrative, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(server_id) DO UPDATE SET 
            context_hash = excluded.context_hash,
            narrative = excluded.narrative,
            updated_at = excluded.updated_at
    """, (server_id, current_hash, narrative, now))
    
    conn.commit()
    conn.close()

# Initialize DB when module is imported
init_db()
