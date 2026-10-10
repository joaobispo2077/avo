from pathlib import Path

import pytest

from avo import validate_dependencies, validate_usability


@pytest.mark.parametrize("validator", [validate_dependencies, validate_usability])
def test_validator_config_fallback_contract(tmp_path, validator):
    lookup = validator.validation_config_path
    nested = tmp_path / "config" / "test.json"
    legacy = tmp_path / "test.json"
    assert lookup(tmp_path, "test.json") == nested
    legacy.write_text("{}", encoding="utf-8")
    assert lookup(tmp_path, "test.json") == legacy
    nested.parent.mkdir()
    nested.write_text("{}", encoding="utf-8")
    assert lookup(tmp_path, "test.json") == nested
    assert isinstance(lookup(tmp_path, "test.json"), Path)
