"""Compatibility shim — remove in v0.2.0. Use `avo.transcribe_batch`."""
import warnings

warnings.warn(
    "helpers.transcribe_batch.py is deprecated; use avo.transcribe_batch",
    DeprecationWarning,
    stacklevel=2,
)
from avo.transcribe_batch import *  # noqa: F403
