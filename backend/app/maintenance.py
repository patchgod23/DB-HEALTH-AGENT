"""
maintenance.py — Execution engine for maintenance scripts.
Handles loading SQL files and executing them on target servers with dynamic name replacement.
"""
import os
import re
from loguru import logger
from app.db import DBConnection
from app.config import load_config

SCRIPTS_DIR = "db"

def get_log_file_name(conn: DBConnection, db_name: str) -> str:
    """Queries SQL Server to find the logical name of the log file."""
    query = "SELECT name FROM sys.master_files WHERE database_id = DB_ID(?) AND type_desc = 'LOG'"
    try:
        rows, _ = conn.execute(query, (db_name,))
        if rows:
            return rows[0][0]
    except Exception as e:
        logger.error(f"Error buscando nombre lógico del log: {e}")
    return f"{db_name}_LOG" # Fallback

def execute_maintenance_script(server_id: str, script_name: str) -> dict:
    """Loads a script, replaces DB and LOG names dynamically, and executes it."""
    agent_config = load_config()
    server = next((s for s in agent_config.servers if s.id == server_id), None)
    
    if not server:
        return {"success": False, "error": f"Servidor {server_id} no encontrado."}
        
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        return {"success": False, "error": f"Script {script_name} no existe en la carpeta db/."}
        
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            sql_content = f.read()
            
        conn = DBConnection(server)
        conn.connect()
        
        # Obtenemos el nombre del log real para el shrink
        log_logical_name = get_log_file_name(conn, server.database)
        
        # REEMPLAZO DINÁMICO PRO:
        # 1. Cambiamos cualquier mención de MAXPOINT_K130 por la DB real (ej: WD44)
        sql_final = sql_content.replace("MAXPOINT_K130", server.database)
        
        # 2. Cambiamos específicamente el nombre del archivo de log si aparece
        # Buscamos patrones como MAXPOINT_K130_LOG o similares
        sql_final = sql_final.replace(f"{server.database}_LOG", log_logical_name)
        
        # Dividimos por GO
        commands = re.split(r'\bGO\b', sql_final, flags=re.IGNORECASE)
        
        for cmd in commands:
            clean_cmd = cmd.strip()
            if clean_cmd:
                logger.info(f"[{server_id}] Ejecutando bloque en {server.database}: {clean_cmd[:50]}...")
                conn.execute(clean_cmd)
                
        conn.close()
        return {"success": True, "message": f"Script {script_name} ejecutado con éxito en {server.database} (Log: {log_logical_name})"}
        
    except Exception as e:
        logger.error(f"Error ejecutando mantenimiento: {e}")
        return {"success": False, "error": str(e)}
