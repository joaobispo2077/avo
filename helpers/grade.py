"""Compatibility shim — remove in v0.2.0. Use `avo.grade`."""
import warnings

warnings.warn(
    "helpers.grade.py is deprecated; use avo.grade",
    DeprecationWarning,
    stacklevel=2,
)
from avo.grade import *  # noqa: F403
