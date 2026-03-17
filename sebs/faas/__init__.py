# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Main interfaces for FaaS system implementation.

For each cloud platform, we implement system abstractions characteristics
creates and manages functions; resource management; object storage;
NoSQL storage; and function abstraction.
"""
from .system import System  # noqa
from .storage import PersistentStorage  # noqa
