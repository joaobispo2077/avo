"""Mark every collected test under tests/integration as integration scope.

pytestmark in conftest.py is ignored; apply the marker during collection so
unit/coverage `-m "not integration"` and path ignore both stay consistent.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.integration
    for item in items:
        path = Path(str(getattr(item, "path", None) or item.fspath))
        if "integration" in path.parts:
            item.add_marker(marker)
