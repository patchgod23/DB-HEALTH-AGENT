import os
import sys
from pathlib import Path
from loguru import logger

# Aseguramos que la raíz esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DBConnection
from app.config import load_config

SCRIPTS_DIR = "db"

def execute_maintenance_script(server_id: str, script_name: str) -> dict:
    """Loads a script, replaces DB names dynamically, and executes it."""
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
            
        # Dinamismo: Reemplazamos el nombre de la DB hardcodeado por el real
        # Nota: Esto es una aproximación simple, asumiendo que el script usa USE o nombres de DB comunes.
        # En tus scripts dice MAXPOINT_K130, lo cambiamos por el del servidor actual.
        sql_final = sql_content.replace("MAXPOINT_K130", server.database)
        
        # SQL Server no permite múltiples comandos con GO en un solo execute de pyodbc fácilmente.
        # Dividimos por GO si es necesario o ejecutamos el bloque completo si no tiene GOs complejos.
        # Para simplificar, ejecutaremos el script comando por comando (separados por GO).
        commands = sql_final.split("GO")
        
        conn = DBConnection(server)
        conn.connect()
        
        for cmd in commands:
            clean_cmd = cmd.strip()
            if clean_cmd:
                logger.info(f"[{server_id}] Ejecutando bloque de mantenimiento de {script_name}...")
                conn.execute(clean_cmd)
                
        conn.close()
        return {"success": True, "message": f"Script {script_name} ejecutado con éxito en {server.database}"}
        
    except Exception as e:
        logger.error(f"Error ejecutando mantenimiento: {e}")
        return {"success": False, "error": str(e)}
