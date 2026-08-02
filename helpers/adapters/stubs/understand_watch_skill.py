"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.stubs.understand_watch_skill`."""
import warnings

warnings.warn(
    "helpers.adapters/stubs/understand_watch_skill.py is deprecated; use avo.adapters.stubs.understand_watch_skill",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.stubs.understand_watch_skill import *  # noqa: F403
