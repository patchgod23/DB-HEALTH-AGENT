"""
config.py — Configuration loader for db-health-agent.

Reads from .env and servers.yaml / servers list.
Supports environment variable overrides for all thresholds.
"""
from __future__ import annotations

import os
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


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
    log_format: str = os.getenv("LOG_FORMAT", "json")  # json | sqlite
    run_interval_sec: int = int(os.getenv("RUN_INTERVAL_SEC", 60))
    alert_on_recovery: bool = os.getenv("ALERT_ON_RECOVERY", "true").lower() == "true"
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini") # gemini or openai


def load_config(path: str = "servers.yaml") -> AgentConfig:
    """Load agent configuration from a YAML file.

    Falls back to environment-only configuration if no file is found.
    """
    thresholds = Thresholds()

    if not os.path.exists(path):
        return AgentConfig(thresholds=thresholds)

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    servers = []
    for srv in raw.get("servers", []):
        srv_id = srv.get("id", "").upper().replace("-", "_")
        # Allow full connection override from env vars:
        # DB_<ID>_HOST, DB_<ID>_PORT, DB_<ID>_DATABASE, DB_<ID>_USERNAME, DB_<ID>_PASSWORD
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
        log_dir=raw.get("log_dir", thresholds.model_fields["latency_warning_ms"].default),
        log_format=raw.get("log_format", "json"),
        run_interval_sec=raw.get("run_interval_sec", 60),
        alert_on_recovery=raw.get("alert_on_recovery", True),
    )
