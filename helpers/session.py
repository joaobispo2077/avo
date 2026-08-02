"""Compatibility shim — remove in v0.2.0. Use `avo.session`."""
import warnings

warnings.warn(
    "helpers.session.py is deprecated; use avo.session",
    DeprecationWarning,
    stacklevel=2,
)
from avo.session import *  # noqa: F403

if __name__ == "__main__":
    from avo.session import main

    raise SystemExit(main())
