"""Mark every test under tests/integration as integration scope."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration
