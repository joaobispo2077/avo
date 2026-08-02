# helpers/models.py — SHIM; remove in v0.2.0
import warnings

warnings.warn(
    "helpers.models is deprecated; use from avo.models or python -m avo.models_cli",
    DeprecationWarning,
    stacklevel=2,
)
from avo import models as _avo_models
from avo.models import *  # noqa: F403

# Private helpers kept for existing test patches (task 2.5 will migrate mocks).
_hardware_tier = _avo_models._hardware_tier
avo_state = _avo_models.avo_state
