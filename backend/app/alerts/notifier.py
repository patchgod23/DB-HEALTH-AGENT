"""
notifier.py — Alert dispatcher for db-health-agent.

MVP supports:
  - Console alerts (always active)
  - Log-based alerts (written via loguru)

Future phases (Fase 2):
  - Email via SMTP
  - Slack webhook
  - Microsoft Teams webhook
"""
from __future__ import annotations

import os
from datetime import datetime

from loguru import logger

from app.models.result import ServerDiagnosis, Severity

# ANSI color codes for console output
_COLORS = {
    Severity.OK:       "\033[92m",  # green
    Severity.WARNING:  "\033[93m",  # yellow
    Severity.CRITICAL: "\033[91m",  # red
    Severity.UNKNOWN:  "\033[90m",  # grey
}
_RESET = "\033[0m"
_BOLD  = "\033[1m"

# Severity icons
_ICONS = {
    Severity.OK:       "✅",
    Severity.WARNING:  "⚠️ ",
    Severity.CRITICAL: "🚨",
    Severity.UNKNOWN:  "❓",
}


def _console_alert(diagnosis: ServerDiagnosis) -> None:
    """Print a formatted, color-coded alert to stdout."""
    sev = diagnosis.overall_severity
    color = _COLORS.get(sev, "")
    icon = _ICONS.get(sev, "")
    ts = diagnosis.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    border = "─" * 60
    print(f"\n{color}{border}{_RESET}")
    print(
        f"{_BOLD}{color}{icon}  [{sev.value}] {diagnosis.server_id.upper()}{_RESET}"
        f"  |  {diagnosis.host}/{diagnosis.database}"
    )
    print(f"    {ts}")
    print(f"{color}{border}{_RESET}")

    for check in diagnosis.checks:
        check_color = _COLORS.get(check.severity, "")
        check_icon  = _ICONS.get(check.severity, "")
        print(
            f"  {check_color}{check_icon}  {check.check_name:<20} "
            f"{check.severity.value:<8}  {check.message}{_RESET}"
        )

    if diagnosis.summary:
        print(f"\n  {_BOLD}Diagnóstico determinístico/heurístico:{_RESET}")
        for line in diagnosis.summary.split("\n"):
            print(f"    {line}")

    if diagnosis.llm_narrative:
        import textwrap
        print(f"\n  {_BOLD}🧠 Razonamiento IA (Context Layer):{_RESET}")
        wrapped = textwrap.fill(diagnosis.llm_narrative, width=80, subsequent_indent="    ", initial_indent="    ")
        print(wrapped)

    if diagnosis.total_duration_ms is not None:
        print(f"\n  Tiempo total de escaneo: {diagnosis.total_duration_ms:.1f}ms")

    print(f"{color}{border}{_RESET}\n")


def notify(diagnosis: ServerDiagnosis) -> None:
    """Dispatch alerts based on severity.

    Always prints to console. Logs CRITICAL/WARNING via loguru.
    """
    _console_alert(diagnosis)

    sev = diagnosis.overall_severity

    if sev == Severity.CRITICAL:
        logger.critical(
            f"[{diagnosis.server_id}] CRITICAL — {diagnosis.summary.splitlines()[0] if diagnosis.summary else 'Ver checks.'}"
        )
    elif sev == Severity.WARNING:
        logger.warning(
            f"[{diagnosis.server_id}] WARNING — {diagnosis.summary.splitlines()[0] if diagnosis.summary else 'Ver checks.'}"
        )
    else:
        logger.info(f"[{diagnosis.server_id}] OK — Todos los checks pasaron.")


def notify_all(diagnoses: list[ServerDiagnosis]) -> None:
    """Send alerts for a batch of server diagnoses.

    Prints a summary table at the end.
    """
    for diagnosis in diagnoses:
        notify(diagnosis)

    # Summary table
    _print_summary(diagnoses)


def _print_summary(diagnoses: list[ServerDiagnosis]) -> None:
    """Print a compact summary table for all servers."""
    if not diagnoses:
        return

    print(f"\n{'─'*60}")
    print(f"  {'RESUMEN':^56}")
    print(f"{'─'*60}")
    print(f"  {'SERVIDOR':<20} {'BD':<20} {'ESTADO':<10}")
    print(f"  {'─'*18} {'─'*18} {'─'*8}")

    for d in diagnoses:
        sev = d.overall_severity
        color = _COLORS.get(sev, "")
        icon  = _ICONS.get(sev, "")
        print(
            f"  {d.server_id:<20} {d.database:<20} "
            f"{color}{icon} {sev.value:<8}{_RESET}"
        )

    critical = sum(1 for d in diagnoses if d.overall_severity == Severity.CRITICAL)
    warning  = sum(1 for d in diagnoses if d.overall_severity == Severity.WARNING)
    ok       = sum(1 for d in diagnoses if d.overall_severity == Severity.OK)

    print(f"{'─'*60}")
    print(f"  Servidores: {len(diagnoses)} | ✅ {ok} | ⚠️  {warning} | 🚨 {critical}")
    print(f"{'─'*60}\n")
