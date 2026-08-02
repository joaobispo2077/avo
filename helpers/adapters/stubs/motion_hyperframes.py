"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.stubs.motion_hyperframes`."""
import warnings

warnings.warn(
    "helpers.adapters/stubs/motion_hyperframes.py is deprecated; use avo.adapters.stubs.motion_hyperframes",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.stubs.motion_hyperframes import *  # noqa: F403
