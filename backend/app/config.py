"""
config.py — Configuration loader for db-health-agent.

Reads from .env and servers.yaml / servers list.
Supports environment variable overrides for all thresholds.
"""
from __future__ import annotations

import os
from typing import Optional

import yaml
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Buscamos el .env en el directorio actual o en los padres (útil si se corre desde backend/)
def _load_env_robustly():
    current = Path(__file__).resolve().parent
    for _ in range(3):
        env_path = current / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            return
        current = current.parent
    load_dotenv() # Fallback al default

_load_env_robustly()

class ServerConfig(BaseModel):
    """Configuration for a single monitored database server."""

    id: str
    host: str
    port: int = 1433
    database: str
    username: str
    password: str
    driver: str = "ODBC Driver 17 for SQL Server"
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    ignore_freshness_tables: list[str] = Field(default_factory=list)
    table_profiles: dict[str, str] = Field(default_factory=dict)


class Thresholds(BaseModel):
    """Configurable severity thresholds for health checks."""

    # Latency thresholds (ms)
    latency_warning_ms: float = float(os.getenv("LATENCY_WARNING_MS", 1000))
    latency_critical_ms: float = float(os.getenv("LATENCY_CRITICAL_MS", 3000))

    # Freshness thresholds (hours)
    freshness_warning_hours: float = float(os.getenv("FRESHNESS_WARNING_HOURS", 24))
    freshness_critical_hours: float = float(os.getenv("FRESHNESS_CRITICAL_HOURS", 48))

    # Row count: % drop to trigger alert
    rowcount_warning_drop_pct: float = float(os.getenv("ROWCOUNT_WARNING_DROP_PCT", 10))
    rowcount_critical_drop_pct: float = float(os.getenv("ROWCOUNT_CRITICAL_DROP_PCT", 30))

    # Connection timeout (seconds)
    connect_timeout_sec: int = int(os.getenv("CONNECT_TIMEOUT_SEC", 5))

    # Error pattern: max errors in log window
    error_warning_count: int = int(os.getenv("ERROR_WARNING_COUNT", 5))
    error_critical_count: int = int(os.getenv("ERROR_CRITICAL_COUNT", 20))

class AgentConfig(BaseModel):
    """Root configuration for the agent."""

    servers: list[ServerConfig] = Field(default_factory=list)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    log_dir: str = os.getenv("LOG_DIR", "logs")
    log_format: str = os.getenv("LOG_FORMAT", "json")
    run_interval_sec: int = int(os.getenv("RUN_INTERVAL_SEC", 60))
    alert_on_recovery: bool = os.getenv("ALERT_ON_RECOVERY", "true").lower() == "true"
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini")
    llm_model: str = os.getenv("LLM_MODEL", "google/gemini-2.0-flash-lite-preview-02-05:free")


def load_config(path: str = "servers.yaml") -> AgentConfig:
    """Load agent configuration from a YAML file.

    Falls back to environment-only configuration if no file is found.
    """
    thresholds = Thresholds()

    # Si no existe en la ruta dada, probamos en la raíz del proyecto
    if not os.path.exists(path):
        alt_path = Path(__file__).resolve().parent.parent / path
        if alt_path.exists():
            path = str(alt_path)

    raw = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    servers = []
    for srv in raw.get("servers", []):
        srv_id = srv.get("id", "").upper().replace("-", "_")
        for field, env_suffix in [
            ("host",     "HOST"),
            ("port",     "PORT"),
            ("database", "DATABASE"),
            ("username", "USERNAME"),
            ("password", "PASSWORD"),
        ]:
            env_key = f"DB_{srv_id}_{env_suffix}"
            if env_key in os.environ:
                srv[field] = os.environ[env_key]
        servers.append(ServerConfig(**srv))

    cfg_thresholds = raw.get("thresholds", {})
    if cfg_thresholds:
        thresholds = Thresholds(**{**thresholds.model_dump(), **cfg_thresholds})

    return AgentConfig(
        servers=servers,
        thresholds=thresholds,
        log_dir=raw.get("log_dir", os.getenv("LOG_DIR", "logs")),
        log_format=raw.get("log_format", os.getenv("LOG_FORMAT", "json")),
        run_interval_sec=raw.get("run_interval_sec", int(os.getenv("RUN_INTERVAL_SEC", 60))),
        alert_on_recovery=raw.get("alert_on_recovery", os.getenv("ALERT_ON_RECOVERY", "true").lower() == "true"),
        llm_api_key=raw.get("llm_api_key", os.getenv("LLM_API_KEY")),
        llm_provider=raw.get("llm_provider", os.getenv("LLM_PROVIDER", "gemini")),
        llm_model=raw.get("llm_model", os.getenv("LLM_MODEL", "google/gemini-2.0-flash-lite-preview-02-05:free")),
    )
