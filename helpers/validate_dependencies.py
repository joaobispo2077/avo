"""Compatibility shim — remove in v0.2.0. Use `avo.validate_dependencies`."""
import warnings

warnings.warn(
    "helpers.validate_dependencies.py is deprecated; use avo.validate_dependencies",
    DeprecationWarning,
    stacklevel=2,
)
from avo.validate_dependencies import *  # noqa: F403
