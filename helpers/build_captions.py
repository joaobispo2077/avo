"""Compatibility shim — remove in v0.2.0. Use `avo.build_captions`."""
import warnings

warnings.warn(
    "helpers.build_captions.py is deprecated; use avo.build_captions",
    DeprecationWarning,
    stacklevel=2,
)
from avo.build_captions import *  # noqa: F403
