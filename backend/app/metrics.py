import os
from prometheus_client import start_http_server, Histogram, Counter, Gauge

# Histogramas
SCAN_DURATION = Histogram(
    'dbhealth_scan_duration_seconds',
    'Duracion del escaneo completo de base de datos en segundos',
    ['server_id', 'database']
)

LLM_LATENCY = Histogram(
    'dbhealth_llm_latency_seconds',
    'Latencia de generacion de diagnostico LLM',
    ['server_id', 'provider']
)

# Contadores
LLM_CACHE_HITS = Counter(
    'dbhealth_llm_cache_hits_total',
    'Total de veces que el contexto semantico tuvo hit en SQLite',
    ['server_id']
)

LLM_CACHE_MISSES = Counter(
    'dbhealth_llm_cache_misses_total',
    'Total de veces que el contexto semantico tuvo miss requiriendo API LLM',
    ['server_id']
)

INCIDENTS_TOTAL = Counter(
    'dbhealth_incidents_total',
    'Total de escaneos resultantes en alertas',
    ['server_id', 'severity']
)

CHECKS_TOTAL = Counter(
    'dbhealth_checks_total',
    'Total de checks ejecutados agrupados por status',
    ['server_id', 'check_name', 'status']
)

# Gauges
SQLITE_DB_SIZE = Gauge(
    'dbhealth_sqlite_db_size_bytes',
    'Tamano del archivo de base de datos SQLite de estado local'
)

def start_metrics_server(port: int = 8000):
    """Inicia el servidor HTTP de Prometheus."""
    start_http_server(port)

def update_sqlite_size(db_path: str = "logs/state.db"):
    """Actualiza la metrica del tamaño de la base de datos."""
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        SQLITE_DB_SIZE.set(size)
