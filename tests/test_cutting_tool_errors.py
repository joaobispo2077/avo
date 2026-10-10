"""Tool failures must survive context-manager cleanup with their real cause."""

from contextlib import contextmanager

import pytest

from avo.timeline.ports import ToolError


def test_tool_error_preserves_failure_when_leaving_generator_context():
    @contextmanager
    def resource():
        yield

    with pytest.raises(ToolError, match="decoder failed"):
        with resource():
            raise ToolError("cutting-decode", "decoder failed", False)
