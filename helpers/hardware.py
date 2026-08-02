"""Compatibility shim — remove in v0.2.0. Use `avo.hardware`."""
import warnings

warnings.warn(
    "helpers.hardware.py is deprecated; use avo.hardware",
    DeprecationWarning,
    stacklevel=2,
)
from avo.hardware import *  # noqa: F403
