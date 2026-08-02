"""Compatibility shim — remove in v0.2.0. Use `avo.models_cli`."""
import warnings

warnings.warn(
    "helpers.models_cli.py is deprecated; use avo.models_cli",
    DeprecationWarning,
    stacklevel=2,
)
from avo.models_cli import *  # noqa: F403
