"""
agent.py — Core orchestrator for db-health-agent.

Coordinates the full monitoring cycle:
  1. Load enabled servers
  2. Run all health checks per server
  3. Analyze results
  4. Persist logs
  5. Trigger alerts
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from loguru import logger

from app.alerts.notifier import notify_all
from app.analyzer.rules import analyze
from app.analyzer.llm import generate_diagnosis
from app.checks import connectivity, latency, freshness, rowcount, errors, db_size
from app.config import AgentConfig, ServerConfig, Thresholds
from app.models.result import ServerDiagnosis, Severity
from app.storage.logger import HealthLogger
from app.metrics import (
    start_metrics_server, update_sqlite_size, 
    SCAN_DURATION, INCIDENTS_TOTAL, CHECKS_TOTAL
)


# Ordered list of check functions to run per server
_CHECKS = [
    connectivity.run,
    latency.run,
    freshness.run,
    rowcount.run,
    errors.run,
    db_size.run,
]


def _run_server_checks(
    config: ServerConfig,
    thresholds: Thresholds,
    config_root: AgentConfig | None = None
) -> ServerDiagnosis:
    """Execute all health checks for a single server and return diagnosis."""
    diagnosis = ServerDiagnosis(
        server_id=config.id,
        host=config.host,
        database=config.database,
        overall_severity=Severity.UNKNOWN,
    )

    start_total = time.perf_counter()

    for check_fn in _CHECKS:
        try:
            result = check_fn(config, thresholds)
            diagnosis.add_check(result)
            CHECKS_TOTAL.labels(server_id=config.id, check_name=result.check_name, status=result.severity.value).inc()
            logger.debug(
                f"[{config.id}] {result.check_name}: {result.severity.value} — {result.message}"
            )
        except Exception as exc:
            # Never let a single check crash the whole agent
            logger.error(
                f"[{config.id}] Unhandled error in {check_fn.__module__}: {exc}"
            )

        # Short-circuit: if connectivity failed, skip remaining checks
        if (
            diagnosis.checks
            and diagnosis.checks[-1].check_name == "connectivity"
            and diagnosis.checks[-1].severity == Severity.CRITICAL
        ):
            logger.warning(
                f"[{config.id}] Conectividad CRÍTICA — omitiendo los checks restantes."
            )
            break

    duration_sec = time.perf_counter() - start_total
    diagnosis.total_duration_ms = duration_sec * 1000
    SCAN_DURATION.labels(server_id=config.id, database=config.database).observe(duration_sec)
    
    # Heuristic interpretation + Severity Engine
    final_diagnosis = analyze(diagnosis)
    
    # LLM Reasoning Layer
    if config_root and config_root.llm_api_key:
        final_diagnosis.llm_narrative = generate_diagnosis(
            final_diagnosis, 
            config_root.llm_api_key, 
            config_root.llm_provider,
            config_root.llm_model
        )
        
    return final_diagnosis


class HealthAgent:
    """Autonomous multi-database health monitoring agent."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.storage = HealthLogger(log_dir=config.log_dir)
        try:
            start_metrics_server(port=8000)
            logger.info("Servidor Prometheus Metrics iniciado en el puerto 8000")
        except Exception as e:
            logger.warning(f"No se pudo iniciar el servidor de métricas: {e}")

    def run_once(self) -> list[ServerDiagnosis]:
        """Run a single full monitoring cycle across all enabled servers.

        Returns:
            List of ServerDiagnosis, one per enabled server.
        """
        enabled = [s for s in self.config.servers if s.enabled]

        if not enabled:
            logger.warning("No se encontraron servidores habilitados en la configuración.")
            return []

        logger.info(f"Iniciando escaneo de salud para {len(enabled)} servidor(es)...")
        diagnoses: list[ServerDiagnosis] = []

        # Run checks in parallel (one thread per server)
        with ThreadPoolExecutor(max_workers=min(len(enabled), 10)) as executor:
            futures = {
                executor.submit(
                    _run_server_checks, srv, self.config.thresholds, self.config
                ): srv
                for srv in enabled
            }
            for future in as_completed(futures):
                srv = futures[future]
                try:
                    diagnosis = future.result()
                    diagnoses.append(diagnosis)
                except Exception as exc:
                    logger.error(f"[{srv.id}] Error fatal durante el escaneo: {exc}")

        # Sort: critical first, then warning, then ok
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.WARNING: 1,
            Severity.OK: 2,
            Severity.UNKNOWN: 3,
        }
        diagnoses.sort(key=lambda d: severity_order.get(d.overall_severity, 9))

        # Persist and notify
        self.storage.save_batch(diagnoses)
        notify_all(diagnoses)

        critical_count = sum(1 for d in diagnoses if d.overall_severity == Severity.CRITICAL)
        warning_count  = sum(1 for d in diagnoses if d.overall_severity == Severity.WARNING)
        
        for d in diagnoses:
            if d.overall_severity in (Severity.CRITICAL, Severity.WARNING):
                INCIDENTS_TOTAL.labels(server_id=d.server_id, severity=d.overall_severity.value).inc()
            
            if d.llm_narrative:
                logger.info(f"\n[{d.server_id}] 🩺 DIAGNÓSTICO IA:\n{d.llm_narrative}\n")

        update_sqlite_size()

        logger.info(
            f"Escaneo completo. {len(diagnoses)} servidores | "
            f"🚨 {critical_count} crítico(s) | ⚠️  {warning_count} advertencia(s)"
        )

        return diagnoses

    def run_loop(self) -> None:
        """Continuously monitor servers at the configured interval."""
        interval = self.config.run_interval_sec
        logger.info(
            f"Agente iniciado. Monitoreando {len(self.config.servers)} servidor(es) "
            f"cada {interval}s. Presiona Ctrl+C para detener."
        )
        try:
            while True:
                self.run_once()
                logger.info(f"Próximo escaneo en {interval}s...")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Agente detenido por el usuario.")
