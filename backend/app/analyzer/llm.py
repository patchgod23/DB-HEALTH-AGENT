"""
llm.py — Reasoning layer for the health agent.
Uses LLMs (Gemini, OpenAI or OpenRouter) to generate a human-readable narrative
with a Senior DBA (50 years XP) persona.
"""
import json
import time
import urllib.request
from typing import Any, Optional

from loguru import logger
from app.storage.state import get_cached_llm_narrative, save_llm_narrative
from app.metrics import LLM_CACHE_HITS, LLM_CACHE_MISSES, LLM_LATENCY

def build_context_packet(diagnosis: Any) -> dict[str, Any]:
    """Curates the raw diagnosis into a clean, token-efficient packet for the LLM."""
    # Soporte tanto para objetos (Agent) como dicts (API)
    is_dict = isinstance(diagnosis, dict)
    
    def get_val(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    checks_raw = get_val(diagnosis, "checks", [])
    checks_packet = {}
    
    for c in checks_raw:
        name = get_val(c, "check_name")
        severity = get_val(c, "severity")
        # Si es un enum, sacamos el valor
        if hasattr(severity, "value"):
            severity = severity.value
            
        checks_packet[name] = {
            "status": severity,
            "summary": get_val(c, "message"),
            "value": get_val(c, "value")
        }

    return {
        "server": get_val(diagnosis, "server_id"),
        "database": get_val(diagnosis, "database"),
        "status": get_val(diagnosis, "overall_severity", "UNKNOWN"),
        "checks": checks_packet,
        "recommended_maintenance": get_val(diagnosis, "recommended_actions", [])
    }

def generate_diagnosis(diagnosis: Any, api_key: str, provider: str = "gemini", model: str = None, user_message: Optional[str] = None) -> str | None:
    if not api_key:
        return None
        
    context_packet = build_context_packet(diagnosis)
    
    # Solo usamos caché si NO hay un mensaje del usuario (chat interactivo)
    if not user_message:
        cache_data = get_cached_llm_narrative(diagnosis.server_id, diagnosis)
        if cache_data:
            LLM_CACHE_HITS.labels(server_id=diagnosis.server_id).inc()
            # Restauramos las acciones cacheadas
            diagnosis.recommended_actions = cache_data.get("recommended_actions", [])
            return f"{cache_data['narrative']} (Cached)"
        
    LLM_CACHE_MISSES.labels(server_id=diagnosis.server_id).inc()
        
    logger.debug(f"[{diagnosis.server_id}] LLM Context Packet: {json.dumps(context_packet, ensure_ascii=False)}")
    
    base_prompt = f"""Eres un DBA (Database Administrator) Senior con más de 50 años de experiencia real en SQL Server.
Habla SIEMPRE en ESPAÑOL. No uses inglés bajo ninguna circunstancia.
Has visto de todo, desde los primeros mainframes hasta la nube. Tu tono es directo, profesional, un poco rudo pero extremadamente sabio.

Reglas:
1. Habla como un experto veterano. Usa términos como 'fragmentación', 'logs transaccionales', 'integridad de datos', 'índices' y 'planes de ejecución'.
2. Diagnóstico corto (2-3 líneas).
3. Sigue ESTRICTAMENTE la lista de 'recommended_maintenance'. NUNCA sugieras scripts que no estén ahí.
4. Si ves que el Log es pesado pero el Data está bien, céntrate solo en el SHRINK (Paso 5). No pidas limpiezas innecesarias.
5. NO menciones números técnicos irrelevantes del JSON, resume la situación de salud del motor."""

    if user_message:
        prompt = f"{base_prompt}\n\n[INTERACCIÓN DIRECTA CON EL USUARIO]\nEl usuario te pregunta o comenta: \"{user_message}\"\n\nContexto actual del servidor:\n{json.dumps(context_packet, ensure_ascii=False)}\n\nResponde al usuario directamente con tu sabiduría de 50 años:"
    else:
        prompt = f"{base_prompt}\n\nDictamen del Veterano sobre el estado actual:\n{json.dumps(context_packet, ensure_ascii=False)}\n\nDictamen:"

    start_time = time.perf_counter()
    try:
        if provider.lower() == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'), 
                headers={'Content-Type': 'application/json'}, 
                method='POST'
            )
        elif provider.lower() == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": model or "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4
            }
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'), 
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}, 
                method='POST'
            )
        elif provider.lower() == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            payload = {
                "model": model or "google/gemini-2.0-flash-lite-preview-02-05:free",
                "messages": [{"role": "user", "content": prompt}]
            }
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'), 
                headers={
                    'Content-Type': 'application/json', 
                    'Authorization': f'Bearer {api_key}',
                    'HTTP-Referer': 'https://github.com/db-health-agent',
                }, 
                method='POST'
            )
        # Lista de modelos gratuitos confiables para rotar si uno falla (solo para OpenRouter)
        fallback_models = [
            model,
            "google/gemini-2.0-flash-exp:free",
            "google/gemini-2.0-flash-lite-preview-02-05:free",
            "mistralai/mistral-7b-instruct:free",
            "google/gemini-flash-1.5-exp"
        ] if provider.lower() == "openrouter" else [model]
        
        # Filtramos None y duplicados manteniendo orden
        unique_models = []
        for m in fallback_models:
            if m and m not in unique_models: unique_models.append(m)

        last_exception = None
        for current_model in unique_models:
            logger.info(f"[{diagnosis.server_id}] Intentando IA ({provider}) - Modelo: {current_model}")
            
            # Actualizamos el payload con el modelo actual
            if provider.lower() == "openrouter":
                payload["model"] = current_model
                req.data = json.dumps(payload).encode('utf-8')

            # Lógica de reintento simple para el error 429
            max_retries = 1
            for attempt in range(max_retries + 1):
                try:
                    with urllib.request.urlopen(req, timeout=30) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        llm_latency = time.perf_counter() - start_time
                        LLM_LATENCY.labels(server_id=diagnosis.server_id, provider=provider).observe(llm_latency)
                        
                        if provider.lower() == "gemini":
                            narrative = result['candidates'][0]['content']['parts'][0]['text'].strip()
                        else:
                            narrative = result['choices'][0]['message']['content'].strip()
                            
                        if not user_message:
                            save_llm_narrative(diagnosis.server_id, diagnosis, narrative)
                        return narrative
                except urllib.error.HTTPError as e:
                    resp_body = e.read().decode('utf-8') if e.fp else "No body"
                    if e.code == 429 and attempt < max_retries:
                        time.sleep(2)
                        continue
                    
                    # Si es error de modelo (400/404), probamos el siguiente modelo del fallback
                    if e.code in (400, 404) and provider.lower() == "openrouter":
                        logger.warning(f"[{diagnosis.server_id}] Modelo {current_model} falló ({e.code}). Probando siguiente...")
                        last_exception = e
                        break # Rompe el loop de reintentos 429, va al siguiente modelo
                    
                    logger.error(f"[{diagnosis.server_id}] Error IA ({e.code}): {resp_body}")
                    raise
                except Exception as e:
                    logger.error(f"Error inesperado en llamada IA: {e}")
                    raise
            else:
                # Si terminamos los reintentos 429 sin éxito, seguimos al siguiente modelo
                continue
        
        # Si llegamos aquí es que todos los modelos fallaron
        if last_exception: raise last_exception

                
    except Exception as exc:
        err_msg = f"Error en la consulta al Veterano: {exc}"
        logger.error(f"Fallo al generar diagnóstico IA: {exc}")
        return err_msg
