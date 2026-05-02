# 🛡️ db-health-agent: Autonomous SRE Monitoring Engine

An intelligent, autonomous monitoring agent designed to detect, analyze, and interpret SQL Server health anomalies using deterministic heuristics and LLM-powered reasoning.

![Architecture](https://img.shields.io/badge/Architecture-Monorepo-blue)
![Backend](https://img.shields.io/badge/Backend-Python%20%7C%20FastAPI-green)
![Frontend](https://img.shields.io/badge/Frontend-React%20%7C%20Vite-61dafb)
![AI](https://img.shields.io/badge/AI-Gemini%20%7C%20Semantic%20Cache-orange)

## 🎯 Project Overview

`db-health-agent` moves beyond simple "up/down" monitoring. It implements a layered observability strategy:
1.  **Deterministic Layer:** High-frequency health checks (Connectivity, Latency, Freshness, Row Count, Error Patterns).
2.  **Contextual Layer:** SQLite-based persistence to detect "Slow Bleed" (drift) and anomalies over 1h/24h windows.
3.  **AI Reasoning Layer:** Semantic interpretation of incidents using LLMs (Gemini/OpenAI) to provide human-readable narratives and actionable insights.
4.  **Observability Layer:** Native Prometheus metrics and a sober, high-density SRE console for rapid incident response.

---

## 🏗️ Architecture (Monorepo)

```text
db-health-agent/
├── backend/           # Python Ecosystem
│   ├── app/           # Core Agent (Worker) logic
│   ├── api/           # Read-only State API (FastAPI)
│   └── main.py        # Orchestrator
├── frontend/          # React + Vite Ecosystem
├── logs/              # Shared Persistent State (SQLite/JSON)
└── docker-compose.yml # Full-stack Orchestration
```

### Key Technical Decisions
*   **Worker/API Separation:** The Agent (Write-path) and API (Read-path) run as separate processes to ensure operational stability.
*   **Semantic Caching:** LLM calls are debounced using an *Incident Fingerprint* hash. We only query the AI when the operational state actually changes, reducing costs by ~90%.
*   **Sober UI:** A high-density, dark-themed console designed for speed and "signal-to-noise" ratio, inspired by Grafana and Linear.

---

## 🚀 Getting Started

### 1. Prerequisites
*   Docker & Docker Compose
*   A SQL Server instance (or the provided `sqlserver` container in dev)

### 2. Configuration
Copy the environment template and set your credentials:
```bash
cp .env.example .env
```

Define your servers in `backend/servers.yaml`:
```yaml
servers:
  - id: prod-main
    host: 192.168.1.100
    database: MainDB
    heuristic_profile: rolling  # static, rolling, or derived_state
    enabled: true
```

### 3. Deploy
```bash
docker-compose build
docker-compose up -d
```

---

## 📊 Observability

### Prometheus Metrics
Exposed at `http://localhost:8000/metrics`:
*   `dbhealth_scan_duration_seconds`: Performance of the agent.
*   `dbhealth_llm_cache_hits_total`: Efficiency of the reasoning layer.
*   `dbhealth_incidents_total`: Incident count by severity.

### SRE Console
Access the dashboard at `http://localhost:3000`.
*   **Fleet Overview:** Rapid status scanning across all databases.
*   **Server Detail:** Evidence-first diagnostics with collapsible AI insights.

---

## 🛠️ Tech Stack
*   **Backend:** Python 3.12, FastAPI, Pydantic, Loguru.
*   **Database:** SQL Server (Target), SQLite (Local State).
*   **Frontend:** React 18, Vite, TanStack Query, Lucide icons.
*   **Infrastructure:** Docker, Prometheus.

---
*Created with ❤️ for High-Impact SRE Portfolios.*
