import os
import json
from pathlib import Path
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

app = FastAPI(title="DB Health API", description="Read-only state reader for db-health-agent")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_DIR = Path("logs")
DB_PATH = LOG_DIR / "state.db"

def get_latest_health_records() -> dict:
    """Read the latest health state from the JSON log file."""
    today = date.today().isoformat()
    log_file = LOG_DIR / f"health_{today}.json"
    
    if not log_file.exists():
        return {}
        
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            records = json.load(f)
            
        # Group by server_id and keep only the latest record per server
        latest_state = {}
        for r in records:
            latest_state[r["server_id"]] = r
            
        return latest_state
    except Exception as e:
        print(f"Error reading log file: {e}")
        return {}

def get_latest_llm_narratives() -> dict:
    """Read the cached LLM narratives from SQLite."""
    if not DB_PATH.exists():
        return {}
        
    narratives = {}
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT server_id, narrative, updated_at FROM llm_cache")
        for row in cursor.fetchall():
            narratives[row[0]] = {"narrative": row[1], "updated_at": row[2]}
        conn.close()
    except Exception as e:
        print(f"Error reading sqlite DB: {e}")
        
    return narratives

@app.get("/api/servers")
def get_fleet_overview():
    """Returns the fleet overview with basic health metrics."""
    latest_state = get_latest_health_records()
    
    fleet = []
    for server_id, record in latest_state.items():
        fleet.append({
            "id": server_id,
            "host": record.get("host"),
            "database": record.get("database"),
            "status": record.get("overall_severity"),
            "latency_ms": record.get("total_duration_ms"),
            "last_scan": record.get("timestamp")
        })
        
    return {"fleet": fleet}

@app.get("/api/servers/{server_id}")
def get_server_detail(server_id: str):
    """Returns the full diagnostic details and LLM narrative for a specific server."""
    latest_state = get_latest_health_records()
    record = latest_state.get(server_id)
    
    if not record:
        raise HTTPException(status_code=404, detail="Server state not found")
        
    narratives = get_latest_llm_narratives()
    llm_context = narratives.get(server_id)
    
    return {
        "state": record,
        "ai_context": llm_context
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
