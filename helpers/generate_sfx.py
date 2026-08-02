"""Compatibility shim — remove in v0.2.0. Use `avo.generate_sfx`."""
import warnings

warnings.warn(
    "helpers.generate_sfx.py is deprecated; use avo.generate_sfx",
    DeprecationWarning,
    stacklevel=2,
)
from avo.generate_sfx import *  # noqa: F403
