"""Compatibility shim — remove in v0.2.0. Use `avo.project_inventory`."""
import warnings

warnings.warn(
    "helpers.project_inventory.py is deprecated; use avo.project_inventory",
    DeprecationWarning,
    stacklevel=2,
)
from avo.project_inventory import *  # noqa: F403

if __name__ == "__main__":
    from avo.project_inventory import main

    raise SystemExit(main())
