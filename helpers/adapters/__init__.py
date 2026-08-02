"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.__init__`."""
import warnings

warnings.warn(
    "helpers.adapters/__init__.py is deprecated; use avo.adapters.__init__",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.__init__ import *  # noqa: F403
