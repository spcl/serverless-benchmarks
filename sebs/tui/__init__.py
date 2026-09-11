# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Interactive terminal user interfaces for SeBS.

This package hosts Textual-based TUIs used by the CLI. The first one is the
read-only cache inspector (``sebs resources inspect``), which visualises the
on-disk cache grouped by cloud system and resource class.
"""

from .inspect import ResourceInspectorApp, run_inspector  # noqa: F401
