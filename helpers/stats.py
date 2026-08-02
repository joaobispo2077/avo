"""Compatibility shim — remove in v0.2.0. Use `avo.stats`."""
import warnings

warnings.warn(
    "helpers.stats.py is deprecated; use avo.stats",
    DeprecationWarning,
    stacklevel=2,
)
from avo.stats import *  # noqa: F403

if __name__ == "__main__":
    from avo.stats import main

    raise SystemExit(main())
