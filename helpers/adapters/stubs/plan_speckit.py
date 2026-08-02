"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.stubs.plan_speckit`."""
import warnings

warnings.warn(
    "helpers.adapters/stubs/plan_speckit.py is deprecated; use avo.adapters.stubs.plan_speckit",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.stubs.plan_speckit import *  # noqa: F403
