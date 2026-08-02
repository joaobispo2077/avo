"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.stubs.motion_remotion`."""
import warnings

warnings.warn(
    "helpers.adapters/stubs/motion_remotion.py is deprecated; use avo.adapters.stubs.motion_remotion",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.stubs.motion_remotion import *  # noqa: F403
