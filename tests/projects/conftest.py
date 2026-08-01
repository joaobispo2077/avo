"""Footage-project tests — excluded from default AVO CI.

Run locally when working on a specific edit/spec:
    pytest tests/projects
"""

import pytest

pytestmark = pytest.mark.project
