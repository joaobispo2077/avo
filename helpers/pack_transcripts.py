"""Compatibility shim — remove in v0.2.0. Use `avo.pack_transcripts`."""
import warnings

warnings.warn(
    "helpers.pack_transcripts.py is deprecated; use avo.pack_transcripts",
    DeprecationWarning,
    stacklevel=2,
)
from avo.pack_transcripts import *  # noqa: F403
