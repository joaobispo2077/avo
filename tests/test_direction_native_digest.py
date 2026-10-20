import hashlib

import pytest

from avo.direction.rules import DirectionError
from avo.direction_cli import read_input


def test_native_single_read_rejects_changed_body_at_the_confirmed_path(tmp_path):
    path = tmp_path / "decision.json"
    raw = b'{"scope":"project"}'
    path.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    path.write_bytes(b'{"scope":"provider"}')
    with pytest.raises(DirectionError) as error:
        read_input(path, expected_hash=expected)
    assert error.value.status == "stale"


def test_exact_digest_uses_the_same_buffer_that_gets_parsed(tmp_path):
    path = tmp_path / "decision.json"
    raw = b'{"scope":"project"}'
    path.write_bytes(raw)
    assert read_input(path, expected_hash=hashlib.sha256(raw).hexdigest()) == {
        "scope": "project"
    }
