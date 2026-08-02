"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.base`."""
import warnings

warnings.warn(
    "helpers.adapters/base.py is deprecated; use avo.adapters.base",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.base import *  # noqa: F403
