"""Compatibility shim — remove in v0.2.0. Use `avo.final_transcript_artifacts`."""
import warnings

warnings.warn(
    "helpers.final_transcript_artifacts.py is deprecated; use avo.final_transcript_artifacts",
    DeprecationWarning,
    stacklevel=2,
)
from avo.final_transcript_artifacts import *  # noqa: F403
