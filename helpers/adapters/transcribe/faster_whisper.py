"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.transcribe.faster_whisper`."""
import warnings

warnings.warn(
    "helpers.adapters/transcribe/faster_whisper.py is deprecated; use avo.adapters.transcribe.faster_whisper",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.transcribe.faster_whisper import *  # noqa: F403
