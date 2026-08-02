"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.transcribe.elevenlabs`."""
import warnings

warnings.warn(
    "helpers.adapters/transcribe/elevenlabs.py is deprecated; use avo.adapters.transcribe.elevenlabs",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.transcribe.elevenlabs import *  # noqa: F403
