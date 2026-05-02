"""
logger.py — Persistent storage for health check results.

MVP: writes structured JSON logs to disk.
Each run appends a JSON record to logs/health_<date>.json.

Future phases:
  - SQLite backend
  - PostgreSQL backend
  - TimescaleDB (time-series)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, date
from pathlib import Path

from loguru import logger as _logger

from app.models.result import ServerDiagnosis


class HealthLogger:
    """Persists ServerDiagnosis results as structured JSON."""

    def __init__(self, log_dir: str = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        """Return today's log file path."""
        today = date.today().isoformat()
        return self.log_dir / f"health_{today}.json"

    def save(self, diagnosis: ServerDiagnosis) -> None:
        """Append a single diagnosis to today's log file."""
        record = self._serialize(diagnosis)
        path = self._log_path()

        # Load existing records or start fresh
        records: list[dict] = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (json.JSONDecodeError, IOError):
                records = []

        records.append(record)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, default=str)

        _logger.debug(f"[{diagnosis.server_id}] Result saved → {path}")

    def save_batch(self, diagnoses: list[ServerDiagnosis]) -> None:
        """Persist a full batch of diagnoses (one call per server)."""
        for diagnosis in diagnoses:
            self.save(diagnosis)

    def load_latest(self, server_id: str | None = None) -> list[dict]:
        """Load today's log records, optionally filtered by server_id."""
        path = self._log_path()
        if not path.exists():
            return []

        with open(path, "r", encoding="utf-8") as f:
            records: list[dict] = json.load(f)

        if server_id:
            records = [r for r in records if r.get("server_id") == server_id]

        return records

    def load_by_date(self, target_date: date) -> list[dict]:
        """Load log records for a specific date."""
        path = self.log_dir / f"health_{target_date.isoformat()}.json"
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _serialize(diagnosis: ServerDiagnosis) -> dict:
        """Convert a ServerDiagnosis to a plain dict for JSON storage."""
        return {
            "server_id": diagnosis.server_id,
            "host": diagnosis.host,
            "database": diagnosis.database,
            "overall_severity": diagnosis.overall_severity.value,
            "summary": diagnosis.summary,
            "timestamp": diagnosis.timestamp.isoformat(),
            "total_duration_ms": diagnosis.total_duration_ms,
            "checks": [
                {
                    "check_name": c.check_name,
                    "severity": c.severity.value,
                    "message": c.message,
                    "value": c.value,
                    "threshold": c.threshold,
                    "duration_ms": c.duration_ms,
                    "timestamp": c.timestamp.isoformat(),
                }
                for c in diagnosis.checks
            ],
        }
