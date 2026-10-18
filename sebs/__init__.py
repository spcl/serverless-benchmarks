# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""SeBS package exports, loaded on demand."""

from importlib import import_module

from .version import __version__

__all__ = ["Benchmark", "Cache", "SeBS", "__version__"]

_LAZY_EXPORTS = {
    "SeBS": (".sebs", "SeBS"),
    "Cache": (".cache", "Cache"),
    "Benchmark": (".benchmark", "Benchmark"),
}


def __getattr__(name):
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
