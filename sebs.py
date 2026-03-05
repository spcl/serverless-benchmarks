#!/usr/bin/env python3
"""Backward compatibility wrapper for git clone users.

This script allows users who have cloned the repository to continue using
the traditional ./sebs.py or python sebs.py command. It simply imports and
calls the main() function from the sebs.cli module.

For package installs, users should use the 'sebs' command instead.
"""

from sebs.cli import main

if __name__ == "__main__":
    main()
