"""Compatibility shim — remove in v0.2.0. Use `avo.validate_edl`."""
import warnings

warnings.warn(
    "helpers.validate_edl.py is deprecated; use avo.validate_edl",
    DeprecationWarning,
    stacklevel=2,
)
from avo.validate_edl import *  # noqa: F403
