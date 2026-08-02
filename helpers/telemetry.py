"""Compatibility shim — remove in v0.2.0. Use `avo.telemetry`."""
import warnings

warnings.warn(
    "helpers.telemetry.py is deprecated; use avo.telemetry",
    DeprecationWarning,
    stacklevel=2,
)
from avo.telemetry import *  # noqa: F403

if __name__ == "__main__":
    from avo.telemetry import main

    raise SystemExit(main())
