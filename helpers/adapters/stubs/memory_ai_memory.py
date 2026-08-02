"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.stubs.memory_ai_memory`."""
import warnings

warnings.warn(
    "helpers.adapters/stubs/memory_ai_memory.py is deprecated; use avo.adapters.stubs.memory_ai_memory",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.stubs.memory_ai_memory import *  # noqa: F403
