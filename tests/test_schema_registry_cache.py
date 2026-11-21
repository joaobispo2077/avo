"""Parsed schema reuse stays bound to complete current bytes, never file metadata."""

import json
import os

import pytest
from referencing import Resource

from avo.timeline.contracts import ContractError, validate_document


def schemas(root, *, value_type="string"):
    root.mkdir(parents=True, exist_ok=True)
    parent = root / "root.json"
    parent.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "https://cache.test/root.json",
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"$ref": "value.json"}},
            }
        ),
        encoding="utf-8",
    )
    child = root / "value.json"
    child.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "https://cache.test/value.json",
                "type": value_type,
            }
        ),
        encoding="utf-8",
    )
    return child


def validate(root, value):
    return validate_document({"value": value}, "root.json", root=root)


def test_unchanged_schema_contents_do_not_rebuild_parsed_resources(
    tmp_path, monkeypatch
):
    schemas(tmp_path)
    validate(tmp_path, "first")

    def forbidden(*args, **kwargs):
        pytest.fail("Unchanged schema resources were parsed again")

    monkeypatch.setattr(Resource, "from_contents", forbidden)
    validate(tmp_path, "second")
    with pytest.raises(ContractError):
        validate(tmp_path, 42)


def test_changed_reference_with_restored_size_and_mtime_is_revalidated(tmp_path):
    child = schemas(tmp_path)
    validate(tmp_path, "first")
    previous = child.stat()
    child.write_text(
        child.read_text(encoding="utf-8").replace('"string"', '"number"'),
        encoding="utf-8",
    )
    assert child.stat().st_size == previous.st_size
    os.utime(child, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    validate(tmp_path, 42)
    with pytest.raises(ContractError):
        validate(tmp_path, "old type")


def test_deleted_or_malformed_reference_cannot_use_the_cached_old_contract(tmp_path):
    child = schemas(tmp_path)
    validate(tmp_path, "first")
    original = child.read_bytes()
    child.unlink()
    with pytest.raises(ContractError):
        validate(tmp_path, "missing")
    child.write_text("{broken", encoding="utf-8")
    with pytest.raises(ContractError):
        validate(tmp_path, "malformed")
    child.write_bytes(original)
    validate(tmp_path, "restored")
    (tmp_path / "unrelated.json").write_text(
        "{unrelated broken schema", encoding="utf-8"
    )
    validate(tmp_path, "optional remains independent")


def test_roots_with_the_same_schema_ids_keep_their_actual_content(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    schemas(first)
    schemas(second, value_type="number")
    validate(first, "first root")
    validate(second, 42)
    with pytest.raises(ContractError):
        validate(second, "different root")
    with pytest.raises(ContractError):
        validate(first, 42)
