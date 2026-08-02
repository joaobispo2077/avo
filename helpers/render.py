"""Compatibility shim — remove in v0.2.0. Use `avo.render`."""
import warnings

warnings.warn(
    "helpers.render.py is deprecated; use avo.render",
    DeprecationWarning,
    stacklevel=2,
)
from avo.render import *  # noqa: F403
