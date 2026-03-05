#!/usr/bin/env python3
"""CLI entry point with benchmarks-data validation.

This module provides the main entry point for the SeBS CLI tool.
It handles initialization, including ensuring benchmarks-data is available
before delegating to the full CLI implementation.
"""

import logging


def validate_benchmarks_data():
    """Check and initialize benchmarks-data on first run.

    Returns:
        bool: True if benchmarks-data is available, False otherwise
    """
    from sebs.resource_manager import (
        ensure_benchmarks_data,
        get_benchmarks_data_path
    )

    logger = logging.getLogger("sebs")

    try:
        data_path = get_benchmarks_data_path()
        if data_path.exists() and any(data_path.iterdir()):
            return True

        logger.info("Initializing benchmarks-data...")
        ensure_benchmarks_data()
        return True
    except Exception as e:
        logger.warning(
            f"Failed to initialize benchmarks-data: {e}\n"
            f"Some benchmarks may not work without data.\n"
            f"Manual clone: git clone https://github.com/spcl/serverless-benchmarks-data.git {data_path}"
        )
        return False


def main():
    """Main CLI entry point."""
    from sebs.utils import global_logging
    global_logging()

    # Try to validate benchmarks-data (non-fatal)
    validate_benchmarks_data()

    # Import and run CLI commands
    from sebs.cli_commands import cli
    cli()


if __name__ == "__main__":
    main()
