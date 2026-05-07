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
    
    # Table for LLM caching (Added recommended_actions column)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            server_id TEXT PRIMARY KEY,
            context_hash TEXT NOT NULL,
            narrative TEXT NOT NULL,
            recommended_actions TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Migration: check if recommended_actions column exists
    cursor.execute("PRAGMA table_info(llm_cache)")
    columns = [col[1] for col in cursor.fetchall()]
    if "recommended_actions" not in columns:
        logger.info("Migrando llm_cache: Añadiendo columna recommended_actions")
        cursor.execute("ALTER TABLE llm_cache ADD COLUMN recommended_actions TEXT")
    
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
    """Fetch baseline row counts for specific time windows."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    now = datetime.utcnow()
    t_1h_ago = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    t_24h_ago = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    
    baselines = {"t_prev": None, "t_1h": None, "t_24h": None}
    
    cursor.execute("""
        SELECT row_count FROM rowcount_history 
        WHERE server_id = ? AND table_name = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (server_id, table_name))
    row = cursor.fetchone()
    if row is not None:
        baselines["t_prev"] = row[0]
        
    cursor.execute("""
        SELECT row_count FROM rowcount_history 
        WHERE server_id = ? AND table_name = ? AND timestamp <= ?
        ORDER BY timestamp DESC LIMIT 1
    """, (server_id, table_name, t_1h_ago))
    row = cursor.fetchone()
    if row is not None:
        baselines["t_1h"] = row[0]
        
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
    """Extrae nombres de tablas limpias de los valores del check."""
    entities = set()
    if not isinstance(check.value, dict):
        return []
        
    if check.check_name == "row_count":
        for key in ["critical", "warning", "empty"]:
            for item in check.value.get(key, []):
                table = item.split(" ")[0] if " " in item else item
                entities.add(table)
                
    elif check.check_name == "data_freshness":
        for key in ["critical", "warning"]:
            for item in check.value.get(key, []):
                table = item.split(" ")[0] if " " in item else item
                entities.add(table)
                
    elif check.check_name == "error_patterns":
        if check.value.get("failed_jobs"):
            entities.add("jobs_fallidos")
        if check.value.get("blocked_sessions"):
            entities.add("sesiones_bloqueadas")
            
    return sorted(list(entities))

def get_cached_llm_narrative(server_id: str, diagnosis: Any) -> Optional[dict[str, Any]]:
    """Check if the severity state vector + incident fingerprint matches the last LLM response."""
    def get_val(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    def get_sev(obj):
        sev = get_val(obj, "severity") or get_val(obj, "overall_severity")
        return sev.value if hasattr(sev, "value") else sev

    fingerprint = {
        "status": get_sev(diagnosis),
        "checks": {
            get_val(c, "check_name"): {
                "severity": get_sev(c),
                "value": get_val(c, "value"),
                "entities": _extract_entities(c) if not isinstance(c, dict) else [] # Entities extractor needs object for now
            } for c in get_val(diagnosis, "checks", [])
        }
    }
    state_str = json.dumps(fingerprint, sort_keys=True, default=str)
    current_hash = hashlib.sha256(state_str.encode('utf-8')).hexdigest()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT context_hash, narrative, recommended_actions FROM llm_cache WHERE server_id = ?
    """, (server_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == current_hash:
        narrative = row[1]
        if not narrative or narrative.startswith("Error"):
            return None
            
        return {
            "narrative": narrative,
            "recommended_actions": json.loads(row[2]) if row[2] else []
        }
    
    return None

def save_llm_narrative(server_id: str, diagnosis: Any, narrative: str):
    """Save the new incident fingerprint hash and narrative to SQLite."""
    def get_val(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    def get_sev(obj):
        sev = get_val(obj, "severity") or get_val(obj, "overall_severity")
        return sev.value if hasattr(sev, "value") else sev

    fingerprint = {
        "status": get_sev(diagnosis),
        "checks": {
            get_val(c, "check_name"): {
                "severity": get_sev(c),
                "value": get_val(c, "value"),
                "entities": _extract_entities(c) if not isinstance(c, dict) else []
            } for c in get_val(diagnosis, "checks", [])
        }
    }
    state_str = json.dumps(fingerprint, sort_keys=True, default=str)
    current_hash = hashlib.sha256(state_str.encode('utf-8')).hexdigest()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    
    actions = get_val(diagnosis, "recommended_actions", [])
    actions_json = json.dumps(actions)
    
    cursor.execute("""
        INSERT INTO llm_cache (server_id, context_hash, narrative, recommended_actions, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(server_id) DO UPDATE SET 
            context_hash = excluded.context_hash,
            narrative = excluded.narrative,
            recommended_actions = excluded.recommended_actions,
            updated_at = excluded.updated_at
    """, (server_id, current_hash, narrative, actions_json, now))
    
    conn.commit()
    conn.close()

# Initialize DB when module is imported
init_db()
