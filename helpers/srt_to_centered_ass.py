"""Compatibility shim — remove in v0.2.0. Use `avo.srt_to_centered_ass`."""
import warnings

warnings.warn(
    "helpers.srt_to_centered_ass.py is deprecated; use avo.srt_to_centered_ass",
    DeprecationWarning,
    stacklevel=2,
)
from avo.srt_to_centered_ass import *  # noqa: F403
