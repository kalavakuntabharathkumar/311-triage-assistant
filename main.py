#!/usr/bin/env python3
"""
CLI entry point for the 311 Triage Assistant.
Orchestrates ETL, triage, and can start the dashboard.
"""
import argparse
import logging
import sys
from pathlib import Path

# Ensure local imports work when run as module
sys.path.insert(0, str(Path(__file__).parent))

from etl import run_etl
from triage import run_triage

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def main():
    parser = argparse.ArgumentParser(description="311 Triage Assistant CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ETL subcommand
    etl_parser = subparsers.add_parser("etl", help="Run incremental ETL from NYC 311 API")
    etl_parser.add_argument(
        "--days-back", type=int, default=1, help="How many days back to fetch (default: 1)"
    )
    etl_parser.add_argument(
        "--limit", type=int, default=50000, help="Max records to fetch per run (default: 50000)"
    )

    # Triage subcommand
    triage_parser = subparsers.add_parser("triage", help="Run LLM triage on untriaged records")
    triage_parser.add_argument(
        "--batch-size", type=int, default=100, help="Records per LLM batch (default: 100)"
    )
    triage_parser.add_argument(
        "--use-batch-api", action="store_true", help="Use OpenAI Batch API for cost savings"
    )

    # Dashboard subcommand
    dash_parser = subparsers.add_parser("dashboard", help="Launch Streamlit dashboard")
    dash_parser.add_argument(
        "--port", type=int, default=8501, help="Port to run Streamlit on (default: 8501)"
    )

    # Global options
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )

    args = parser.parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    try:
        if args.command == "etl":
            logger.info(f"Starting ETL for last {args.days_back} days")
            run_etl(days_back=args.days_back, limit=args.limit)
            logger.info("ETL completed successfully")
        elif args.command == "triage":
            logger.info(f"Starting triage with batch size {args.batch_size}")
            run_triage(batch_size=args.batch_size, use_batch_api=args.use_batch_api)
            logger.info("Triage completed successfully")
        elif args.command == "dashboard":
            logger.info(f"Launching dashboard on port {args.port}")
            # Import here to avoid streamlit dependency when not needed
            import subprocess
            subprocess.run(["streamlit", "run", "dashboard.py", f"--server.port={args.port}", "--server.address=0.0.0.0"], check=True)
    except Exception as e:
        logger.exception(f"Command '{args.command}' failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
