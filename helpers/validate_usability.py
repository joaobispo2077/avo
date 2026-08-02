"""Compatibility shim — remove in v0.2.0. Use `avo.validate_usability`."""
import warnings

warnings.warn(
    "helpers.validate_usability.py is deprecated; use avo.validate_usability",
    DeprecationWarning,
    stacklevel=2,
)
from avo.validate_usability import *  # noqa: F403
