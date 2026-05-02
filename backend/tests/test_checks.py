"""
test_checks.py — Unit tests for health check modules using mocked DB connections.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.config import ServerConfig, Thresholds
from app.models.result import Severity


def make_server(id="test-srv") -> ServerConfig:
    return ServerConfig(
        id=id,
        host="localhost",
        port=1433,
        database="TestDB",
        username="sa",
        password="pass",
    )


thresholds = Thresholds(
    latency_warning_ms=500,
    latency_critical_ms=2000,
    connect_timeout_sec=5,
    freshness_warning_hours=24,
    freshness_critical_hours=48,
    rowcount_warning_drop_pct=10,
    rowcount_critical_drop_pct=30,
    error_warning_count=5,
    error_critical_count=20,
)


class TestConnectivityCheck:
    def test_ok_when_connection_succeeds(self):
        from app.checks import connectivity

        with patch("app.checks.connectivity.DBConnection") as MockConn:
            instance = MockConn.return_value
            instance.connect_duration_ms = 45.0

            result = connectivity.run(make_server(), thresholds)

        assert result.severity == Severity.OK
        assert result.check_name == "connectivity"

    def test_critical_when_connection_fails(self):
        from app.checks import connectivity
        from app.db import DBConnectionError

        with patch("app.checks.connectivity.DBConnection") as MockConn:
            instance = MockConn.return_value
            instance.connect.side_effect = DBConnectionError("Host unreachable")

            result = connectivity.run(make_server(), thresholds)

        assert result.severity == Severity.CRITICAL
        assert "Host unreachable" in result.message


class TestLatencyCheck:
    def test_ok_below_warning(self):
        from app.checks import latency

        with patch("app.checks.latency.DBConnection") as MockConn:
            instance = MockConn.return_value
            instance.connect_duration_ms = 10.0
            instance.execute.return_value = ([(1,)], 200.0)

            result = latency.run(make_server(), thresholds)

        assert result.severity == Severity.OK
        assert result.value == 200.0

    def test_warning_above_threshold(self):
        from app.checks import latency

        with patch("app.checks.latency.DBConnection") as MockConn:
            instance = MockConn.return_value
            instance.connect_duration_ms = 10.0
            instance.execute.return_value = ([(1,)], 800.0)

            result = latency.run(make_server(), thresholds)

        assert result.severity == Severity.WARNING

    def test_critical_above_threshold(self):
        from app.checks import latency

        with patch("app.checks.latency.DBConnection") as MockConn:
            instance = MockConn.return_value
            instance.connect_duration_ms = 10.0
            instance.execute.return_value = ([(1,)], 2500.0)

            result = latency.run(make_server(), thresholds)

        assert result.severity == Severity.CRITICAL
