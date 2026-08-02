"""Compatibility shim — remove in v0.2.0. Use `avo.avo_state`."""
import warnings

warnings.warn(
    "helpers.avo_state.py is deprecated; use avo.avo_state",
    DeprecationWarning,
    stacklevel=2,
)
from avo.avo_state import *  # noqa: F403

if __name__ == "__main__":
    from avo.avo_state import main

    raise SystemExit(main())
