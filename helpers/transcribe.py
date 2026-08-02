"""Compatibility shim — remove in v0.2.0. Use `avo.transcribe`."""
import warnings

warnings.warn(
    "helpers.transcribe.py is deprecated; use avo.transcribe",
    DeprecationWarning,
    stacklevel=2,
)
from avo.transcribe import *  # noqa: F403
