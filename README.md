# 🩺 DB-HEALTH-AGENT: Autonomous SRE Monitoring Engine (Portfolio Edition)

> [!NOTE]
> This repository is a **Strategic Portfolio Edition** designed to showcase SRE architecture, database observability, and AI reasoning integration. Some advanced proprietary heuristics and production prompts have been sanitized or simplified for public viewing.

An intelligent, autonomous monitoring agent designed to detect, analyze, and interpret SQL Server health anomalies using deterministic heuristics and LLM-powered reasoning.

[![Python](https://img.shields.io/badge/Backend-Python%20%7C%20FastAPI-green)](https://www.python.org/)
[![React](https://img.shields.io/badge/Frontend-React%20%7C%20Vite-61dafb)](https://reactjs.org/)
[![AI](https://img.shields.io/badge/AI-Gemini%20%7C%20Semantic%20Cache-orange)](https://deepmind.google/technologies/gemini/)

## 🎯 Project Overview

`db-health-agent` moves beyond simple "up/down" monitoring. It implements a layered observability strategy:
1.  **Deterministic Layer:** High-frequency health checks (Connectivity, Latency, Freshness, Row Count, Error Patterns).
2.  **Contextual Layer:** SQLite-based persistence to detect "Slow Bleed" (drift) and anomalies over 1h/24h windows.
3.  **AI Reasoning Layer:** Semantic interpretation of incidents using a "Senior DBA" persona to provide human-readable narratives.
4.  **Interactive Maintenance:** Execute critical tasks (Shrink, Cleanup, Restore) directly via AI chat or one-click actions.
5.  **Observability Layer:** Native Prometheus metrics and a premium dark-mode console for rapid incident response.

---

## 🏗️ Architecture (Monorepo)

```text
db-health-agent/
├── backend/           # Python Ecosystem
│   ├── app/           # Core Agent (Worker) logic & AI Layer
│   ├── api/           # Read-only State API & Interactive Chat
│   ├── db/            # Maintenance SQL Scripts
│   └── main.py        # Entry Point
├── frontend/          # React + Vite Dashboard
├── logs/              # Shared Persistent State (SQLite/JSON)
└── docker-compose.yml # Full-stack Orchestration
```

### Key Technical Decisions
*   **Worker/API Separation:** The Agent (Write-path) and API (Read-path) run as separate processes to ensure operational stability.
*   **Semantic Caching:** LLM calls are debounced using an *Incident Fingerprint* hash. We only query the AI when the state actually changes.
*   **Interactive AI Chat:** A direct communication channel with the "Veterano" persona to analyze and resolve incidents in real-time.
*   **Sober UI:** A high-density, dark-themed console designed for speed and "signal-to-noise" ratio.

---

## 🚀 Getting Started

### 1. Prerequisites
*   Docker & Docker Compose
*   SQL Server connectivity (Target servers)

### 2. Configuration
Copy the environment template and set your `LLM_API_KEY`:
```bash
cp .env.example .env
```

Define your servers in `backend/servers.yaml`.

### 3. Deploy
```bash
docker-compose up --build -d
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
*   **Interactive Chat:** Execute maintenance scripts using natural language.

---

## 📚 Documentation
For detailed architecture, setup, and contribution guides, refer to [DOCUMENTATION.md](DOCUMENTATION.md).

---
*Created with ❤️ for High-Impact SRE Portfolios.*
