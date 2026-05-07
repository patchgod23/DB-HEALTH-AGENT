"""
result.py — Data models for health check results and server diagnostics.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class CheckResult(BaseModel):
    """Result of a single health check."""

    check_name: str
    severity: Severity
    message: str
    value: Optional[Any] = None
    threshold: Optional[Any] = None
    duration_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_ok(self) -> bool:
        return self.severity == Severity.OK

    def is_critical(self) -> bool:
        return self.severity == Severity.CRITICAL


class ServerDiagnosis(BaseModel):
    """Aggregated health report for a single database server."""

    server_id: str
    host: str
    database: str
    overall_severity: Severity
    checks: list[CheckResult] = Field(default_factory=list)
    summary: str = ""
    llm_narrative: Optional[str] = None
    recommended_actions: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_duration_ms: Optional[float] = None

    def add_check(self, result: CheckResult) -> None:
        self.checks.append(result)
        self._recalculate_severity()

    def _recalculate_severity(self) -> None:
        severities = [c.severity for c in self.checks]
        if Severity.CRITICAL in severities:
            self.overall_severity = Severity.CRITICAL
        elif Severity.WARNING in severities:
            self.overall_severity = Severity.WARNING
        elif all(s == Severity.OK for s in severities):
            self.overall_severity = Severity.OK
        else:
            self.overall_severity = Severity.UNKNOWN

    def critical_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == Severity.CRITICAL]

    def warning_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == Severity.WARNING]
