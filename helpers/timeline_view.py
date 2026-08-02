"""Compatibility shim — remove in v0.2.0. Use `avo.timeline_view`."""
import warnings

warnings.warn(
    "helpers.timeline_view.py is deprecated; use avo.timeline_view",
    DeprecationWarning,
    stacklevel=2,
)
from avo.timeline_view import *  # noqa: F403
