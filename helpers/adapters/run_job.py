"""Compatibility shim — remove in v0.2.0. Use `avo.adapters.run_job`."""
import warnings

warnings.warn(
    "helpers.adapters/run_job.py is deprecated; use avo.adapters.run_job",
    DeprecationWarning,
    stacklevel=2,
)
from avo.adapters.run_job import *  # noqa: F403
