"""Compatibility shim — remove in v0.2.0. Use `avo.init_project`."""
import warnings

warnings.warn(
    "helpers.init_project.py is deprecated; use avo.init_project",
    DeprecationWarning,
    stacklevel=2,
)
from avo.init_project import *  # noqa: F403

if __name__ == "__main__":
    from avo.init_project import main

    raise SystemExit(main())
