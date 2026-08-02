"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.registry`."""
import warnings

warnings.warn(
    "helpers.adapters/registry.py is deprecated; use avo.adapters.registry",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.registry import *  # noqa: F403
