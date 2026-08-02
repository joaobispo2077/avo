"""Compatibility shim — remove in v0.2.0. Use `avo.wrap`."""
import warnings

warnings.warn(
    "helpers.wrap.py is deprecated; use avo.wrap",
    DeprecationWarning,
    stacklevel=2,
)
from avo.wrap import *  # noqa: F403

if __name__ == "__main__":
    from avo.wrap import main

    raise SystemExit(main())
