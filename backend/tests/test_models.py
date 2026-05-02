"""
test_models.py — Unit tests for result models and severity logic.
No database connection required.
"""
from datetime import datetime

import pytest

from app.models.result import CheckResult, ServerDiagnosis, Severity


def make_check(name: str, severity: Severity) -> CheckResult:
    return CheckResult(
        check_name=name,
        severity=severity,
        message=f"Test message for {name}",
    )


class TestCheckResult:
    def test_is_ok(self):
        c = make_check("connectivity", Severity.OK)
        assert c.is_ok() is True
        assert c.is_critical() is False

    def test_is_critical(self):
        c = make_check("connectivity", Severity.CRITICAL)
        assert c.is_critical() is True
        assert c.is_ok() is False

    def test_timestamp_set_automatically(self):
        c = make_check("latency", Severity.OK)
        assert isinstance(c.timestamp, datetime)


class TestServerDiagnosis:
    def test_severity_escalates_to_critical(self):
        d = ServerDiagnosis(
            server_id="test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.OK,
        )
        d.add_check(make_check("connectivity", Severity.OK))
        d.add_check(make_check("latency", Severity.WARNING))
        d.add_check(make_check("errors", Severity.CRITICAL))
        assert d.overall_severity == Severity.CRITICAL

    def test_severity_warning_when_no_critical(self):
        d = ServerDiagnosis(
            server_id="test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.OK,
        )
        d.add_check(make_check("connectivity", Severity.OK))
        d.add_check(make_check("latency", Severity.WARNING))
        assert d.overall_severity == Severity.WARNING

    def test_all_ok_stays_ok(self):
        d = ServerDiagnosis(
            server_id="test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.UNKNOWN,
        )
        d.add_check(make_check("connectivity", Severity.OK))
        d.add_check(make_check("latency", Severity.OK))
        assert d.overall_severity == Severity.OK

    def test_critical_checks_filter(self):
        d = ServerDiagnosis(
            server_id="test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.UNKNOWN,
        )
        d.add_check(make_check("connectivity", Severity.OK))
        d.add_check(make_check("errors", Severity.CRITICAL))
        assert len(d.critical_checks()) == 1
        assert len(d.warning_checks()) == 0


class TestAnalyzer:
    def test_analyze_adds_summary(self):
        from app.analyzer.rules import analyze

        d = ServerDiagnosis(
            server_id="test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.UNKNOWN,
        )
        d.add_check(make_check("connectivity", Severity.OK))
        d.add_check(make_check("latency", Severity.WARNING))

        result = analyze(d)
        assert result.summary != ""
        assert "WARNING" in result.summary

    def test_analyze_empty_diagnosis(self):
        from app.analyzer.rules import analyze

        d = ServerDiagnosis(
            server_id="test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.UNKNOWN,
        )
        result = analyze(d)
        assert "No checks" in result.summary


class TestHealthLogger:
    def test_save_and_load(self, tmp_path):
        from app.storage.logger import HealthLogger

        hl = HealthLogger(log_dir=str(tmp_path))
        d = ServerDiagnosis(
            server_id="unit-test",
            host="localhost",
            database="TestDB",
            overall_severity=Severity.OK,
            summary="All good",
        )
        d.add_check(make_check("connectivity", Severity.OK))

        hl.save(d)
        records = hl.load_latest(server_id="unit-test")

        assert len(records) == 1
        assert records[0]["server_id"] == "unit-test"
        assert records[0]["overall_severity"] == "OK"
        assert len(records[0]["checks"]) == 1
