"""
main.py — Entry point for db-health-agent.

Usage:
    python main.py                    # Single scan run
    python main.py --loop             # Continuous monitoring loop
    python main.py --config path.yaml # Custom config file
    python main.py --server srv_id    # Scan a single server
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from app.agent import HealthAgent
from app.config import load_config


def _setup_logger(log_dir: str) -> None:
    """Configure loguru: stderr + rotating file."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()  # Remove default handler

    # Console: INFO and above
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level:<8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
        colorize=True,
    )

    # File: DEBUG and above, rotated daily
    logger.add(
        f"{log_dir}/agent_{{time:YYYY-MM-DD}}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} — {message}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="db-health-agent — Autonomous multi-database health monitor"
    )
    parser.add_argument(
        "--config",
        default="servers.yaml",
        help="Path to servers YAML config (default: servers.yaml)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously at the configured interval",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Only scan a specific server ID",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    _setup_logger(config.log_dir)

    logger.info("db-health-agent starting up...")
    logger.info(f"Loaded {len(config.servers)} server(s) from {args.config}")

    # Filter to single server if requested
    if args.server:
        config.servers = [s for s in config.servers if s.id == args.server]
        if not config.servers:
            logger.error(f"No server found with id '{args.server}'. Check servers.yaml.")
            sys.exit(1)
        logger.info(f"Targeting single server: {args.server}")

    agent = HealthAgent(config)

    if args.loop:
        agent.run_loop()
    else:
        diagnoses = agent.run_once()
        # Exit with non-zero code if any critical found (useful for CI/CD)
        from app.models.result import Severity
        if any(d.overall_severity == Severity.CRITICAL for d in diagnoses):
            sys.exit(2)


if __name__ == "__main__":
    main()
