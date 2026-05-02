"""
llm.py — Reasoning layer for the health agent.
Uses LLMs (Gemini or OpenAI) to generate a human-readable narrative
from the deterministic context packet. Does NOT alter severity.
"""
import json
import time
import urllib.request
from typing import Any

from loguru import logger
from app.storage.state import get_cached_llm_narrative, save_llm_narrative
from app.metrics import LLM_CACHE_HITS, LLM_CACHE_MISSES, LLM_LATENCY

def build_context_packet(diagnosis: Any) -> dict[str, Any]:
    """Curates the raw diagnosis into a clean, token-efficient packet for the LLM."""
    return {
        "server": diagnosis.server_id,
        "database": diagnosis.database,
        "status": diagnosis.overall_severity.value,
        "checks": {
            c.check_name: {
                "status": c.severity.value,
                "summary": c.message,
                "value": c.value
            } for c in diagnosis.checks
        }
    }

def generate_diagnosis(diagnosis: Any, api_key: str, provider: str = "gemini") -> str | None:
    if not api_key:
        return None
        
    context_packet = build_context_packet(diagnosis)
    
    # 4. Debouncing: Check if severity state has changed
    cached_narrative = get_cached_llm_narrative(diagnosis.server_id, diagnosis)
    if cached_narrative:
        LLM_CACHE_HITS.labels(server_id=diagnosis.server_id).inc()
        return f"{cached_narrative} (Cached)"
        
    LLM_CACHE_MISSES.labels(server_id=diagnosis.server_id).inc()
        
    # 5. Loguear el context packet exacto (Debug)
    logger.debug(f"[{diagnosis.server_id}] LLM Context Packet (Nuevo): {json.dumps(context_packet, ensure_ascii=False)}")
    
    prompt = f"""Eres un experto DBA Senior y analista de confiabilidad (SRE).
Se te entregará un paquete de contexto (JSON) con los resultados determinísticos de un agente de monitoreo para una base de datos SQL Server.
Tu única tarea es proporcionar un diagnóstico situacional corto (2 a 3 líneas) y muy profesional.
NO repitas los números exactos ni las métricas, resume la situación.
DEBES usar la heurística proporcionada:
- Si ves tablas 'derived_state' cayendo fuertemente o vacías, asume un recálculo/rebuild normal. NO es un incidente de pérdida de datos.
- Si ves tablas 'rolling' cayendo, asume una purga de mantenimiento normal (purge/archive).
- Si la latencia, conectividad y errores están OK, enfatiza que el motor está sano.
- NUNCA cambies ni cuestiones la severidad final (status), solo explícala.

Context Packet:
{json.dumps(context_packet, ensure_ascii=False)}
"""

    # 5 y 7. Timeout agresivo y medición de latencia
    start_time = time.perf_counter()
    try:
        if provider.lower() == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'), 
                headers={'Content-Type': 'application/json'}, 
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                result = json.loads(response.read().decode('utf-8'))
                llm_latency = time.perf_counter() - start_time
                LLM_LATENCY.labels(server_id=diagnosis.server_id, provider='gemini').observe(llm_latency)
                logger.debug(f"[{diagnosis.server_id}] LLM (Gemini) resolvió en {llm_latency:.2f}s")
                narrative = result['candidates'][0]['content']['parts'][0]['text'].strip()
                save_llm_narrative(diagnosis.server_id, diagnosis, narrative)
                return narrative
                
        elif provider.lower() == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2
            }
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'), 
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}, 
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.loads(response.read().decode('utf-8'))
                llm_latency = time.perf_counter() - start_time
                LLM_LATENCY.labels(server_id=diagnosis.server_id, provider='openai').observe(llm_latency)
                logger.debug(f"[{diagnosis.server_id}] LLM (OpenAI) resolvió en {llm_latency:.2f}s")
                narrative = result['choices'][0]['message']['content'].strip()
                save_llm_narrative(diagnosis.server_id, diagnosis, narrative)
                return narrative
                
        else:
            logger.warning(f"LLM provider {provider} no soportado.")
            return None
            
    except Exception as exc:
        logger.error(f"Fallo al generar diagnóstico IA: {exc}")
        return None
