"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.transcribe.__init__`."""
import warnings

warnings.warn(
    "helpers.adapters/transcribe/__init__.py is deprecated; use avo.adapters.transcribe.__init__",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.transcribe.__init__ import *  # noqa: F403
