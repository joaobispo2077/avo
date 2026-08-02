"""Compatibility shim — remove in v0.2.0. Use `avo.prepare_transcription`."""
import warnings

warnings.warn(
    "helpers.prepare_transcription.py is deprecated; use avo.prepare_transcription",
    DeprecationWarning,
    stacklevel=2,
)
from avo.prepare_transcription import *  # noqa: F403
