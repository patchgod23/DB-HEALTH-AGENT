"""
rules.py — Diagnostic analyzer for aggregated health check results.

Converts raw CheckResult objects into a human-readable diagnosis
with severity classification and actionable recommendations.
"""
from __future__ import annotations

from app.models.result import CheckResult, ServerDiagnosis, Severity


# Severity priority for ranking (higher = worse)
_SEVERITY_RANK = {
    Severity.OK: 0,
    Severity.UNKNOWN: 1,
    Severity.WARNING: 2,
    Severity.CRITICAL: 3,
}

# Per-check recommendations surfaced in the diagnosis
_RECOMMENDATIONS: dict[str, dict[Severity, str]] = {
    "connectivity": {
        Severity.CRITICAL: "Verifica el host/puerto, las reglas del firewall y las credenciales.",
    },
    "query_latency": {
        Severity.WARNING: "Monitorea contención de recursos. Revisa CPU, memoria y consultas activas.",
        Severity.CRITICAL: "Investiga sesiones bloqueadas, índices faltantes o cuellos de botella de hardware.",
    },
    "data_freshness": {
        Severity.WARNING: "Validar si corresponden a catálogos/eventos de baja frecuencia ('warm data') antes de escalar.",
        Severity.CRITICAL: "Los ETLs probablemente se detuvieron. Investiga los feeds de origen y los logs de los trabajos.",
    },
    "row_count": {
        Severity.WARNING: "Reducción de volumen o tablas vacías. Posible purge operacional o recálculo transitorio de tablas derivadas. Validar tendencia.",
        Severity.CRITICAL: "Caída masiva de datos fuera de los rangos de retención normal o truncamiento a cero.",
    },
    "error_patterns": {
        Severity.WARNING: "Revisa el historial de trabajos del Agente SQL y sesiones bloqueadas.",
        Severity.CRITICAL: "Múltiples fallos o bloqueos pesados detectados. Se requiere investigación inmediata.",
    },
}


def analyze(diagnosis: ServerDiagnosis) -> ServerDiagnosis:
    """Enrich a ServerDiagnosis with a summary and recommendations.

    Args:
        diagnosis: A ServerDiagnosis with checks already populated.

    Returns:
        The same diagnosis object, mutated with summary text.
    """
    if not diagnosis.checks:
        diagnosis.summary = "No se ejecutaron checks."
        return diagnosis

    # Recalculate overall severity (checks may have been added externally)
    worst = max(diagnosis.checks, key=lambda c: _SEVERITY_RANK[c.severity])
    diagnosis.overall_severity = worst.severity

    # Build summary lines
    lines: list[str] = []

    ok_count = sum(1 for c in diagnosis.checks if c.severity == Severity.OK)
    warn_count = sum(1 for c in diagnosis.checks if c.severity == Severity.WARNING)
    crit_count = sum(1 for c in diagnosis.checks if c.severity == Severity.CRITICAL)

    lines.append(
        f"Se ejecutaron {len(diagnosis.checks)} check(s): "
        f"{ok_count} OK | {warn_count} WARNING | {crit_count} CRITICAL"
    )

    # Surface top issues with recommendations
    issues = [c for c in diagnosis.checks if c.severity != Severity.OK]
    issues.sort(key=lambda c: _SEVERITY_RANK[c.severity], reverse=True)

    for check in issues:
        rec = _RECOMMENDATIONS.get(check.check_name, {}).get(check.severity, "")
        line = f"[{check.severity.value}] {check.check_name}: {check.message}"
        if rec:
            line += f" → {rec}"
        lines.append(line)

    diagnosis.summary = "\n".join(lines)
    return diagnosis
