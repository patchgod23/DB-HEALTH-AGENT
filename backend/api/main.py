import json
import sys
from pathlib import Path
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

# Importación local
try:
    from api.maintenance import execute_maintenance_script
except ImportError:
    from maintenance import execute_maintenance_script

from app.analyzer.llm import generate_diagnosis
from app.config import load_config
from loguru import logger

api_app = FastAPI(title="DB Health API", description="Read-only state reader for db-health-agent")

# Enable CORS for frontend
api_app.add_middleware(
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

@api_app.get("/api/servers")
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

@api_app.get("/api/servers/{server_id}")
def get_server_detail(server_id: str):
    """Returns the full diagnostic details and LLM narrative for a specific server."""
    latest_state = get_latest_health_records()
    record = latest_state.get(server_id)
    
    if not record:
        raise HTTPException(status_code=404, detail="Server state not found")
        
    from app.storage.state import get_cached_llm_narrative
    # Validamos si la narrativa cacheada corresponde al estado actual (hash match)
    llm_context = get_cached_llm_narrative(server_id, record)
    
    return {
        "state": record,
        "ai_context": llm_context
    }

@api_app.post("/api/maintenance/run")
def run_maintenance(server_id: str, script_name: str):
    """Executes a suggested maintenance script on the target server."""
    logger.info(f"Manual maintenance request: {server_id} -> {script_name}")
    result = execute_maintenance_script(server_id, script_name)
    if not result["success"]:
        # No lanzamos 500 para que el front pueda mostrar el error amigablemente
        return {"success": False, "error": result["error"]}
    return result

@api_app.post("/api/chat")
def chat_with_senior(server_id: str, message: str):
    """Chat with the Senior DBA about a specific server and optionally run scripts."""
    try:
        latest_state = get_latest_health_records()
        record = latest_state.get(server_id)
        if not record:
            raise HTTPException(status_code=404, detail="Server state not found")
            
        config = load_config()
        recommended = record.get("recommended_actions", [])
        
        execution_result = None
        target_script = None
        msg_lower = message.lower()
        
        # Detección de intención de ejecución (más flexible: ignora espacios y extensiones)
        msg_no_spaces = msg_lower.replace(" ", "")
        for action in recommended:
            clean_action = action.lower()
            base_action = clean_action.replace(".sql", "")
            base_no_dots = base_action.split('.')[-1] # "shrinkdb"
            
            if (clean_action in msg_lower or 
                base_action in msg_lower or 
                base_no_dots in msg_no_spaces):
                target_script = action
                break
                
        if target_script:
            from api.maintenance import execute_maintenance_script
            logger.info(f"Chat-triggered execution for {server_id}: {target_script}")
            try:
                execution_result = execute_maintenance_script(server_id, target_script)
            except Exception as e:
                execution_result = {"success": False, "error": f"Error inesperado en ejecución: {e}"}

        # Verificamos si tenemos API Key
        if not config.llm_api_key:
            logger.error("LLM_API_KEY no encontrada en la configuración de la API.")
            return {
                "response": "Lo siento, no tengo configurada mi llave de API (LLM_API_KEY). Por favor, revisa el archivo .env.",
                "executed": target_script is not None,
                "execution_result": execution_result
            }

        # Re-empaquetamos para la IA
        class MockDiagnosis:
            def __init__(self, r):
                self.server_id = r["server_id"]
                self.database = r["database"]
                self.overall_severity = r["overall_severity"]
                self.checks = r.get("checks", [])
                self.recommended_actions = r.get("recommended_actions", [])

        # Contexto de ejecución para el Veterano
        execution_context = ""
        if target_script and execution_result:
            status_text = "ÉXITO" if execution_result.get("success") else "FALLO"
            detail = execution_result.get("message") or execution_result.get("error")
            execution_context = f"\n\n[SISTEMA: El usuario solicitó ejecutar '{target_script}'. El script se ha intentado ejecutar. Resultado: {status_text}. Detalle: {detail}]"
        elif target_script:
             execution_context = f"\n\n[SISTEMA: El usuario solicitó ejecutar '{target_script}' pero el motor de ejecución no devolvió respuesta.]"

        # Llamada a la IA
        from app.analyzer.llm import generate_diagnosis
        res = generate_diagnosis(
            MockDiagnosis(record), 
            config.llm_api_key, 
            config.llm_provider, 
            config.llm_model, 
            user_message=f"{message}{execution_context}"
        )
        
        return {
            "response": res, 
            "executed": target_script is not None,
            "execution_result": execution_result
        }
    except Exception as e:
        logger.exception(f"Error fatal en chat_with_senior: {e}")
        return {
            "response": f"El Veterano tuvo un mareo técnico (Error 500): {e}",
            "executed": False,
            "execution_result": None
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api_app, host="0.0.0.0", port=8080)
