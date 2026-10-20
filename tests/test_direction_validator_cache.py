"""Repeated schema checking cannot hide changed schemas or instances."""

import json
import os

import jsonschema
import pytest

from avo.timeline.contracts import ContractError, validate_document


def schema_file(tmp_path, kind="string"):
    value = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:avo:cache:" + tmp_path.name,
        "type": "object",
        "additionalProperties": False,
        "properties": {"value": {"type": kind}},
        "required": ["value"],
    }
    path = tmp_path / "cache.schema.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_repeated_checks_reuse_schema_compilation_but_revalidate_instances(
    tmp_path, monkeypatch
):
    schema_file(tmp_path)
    count = []
    original = jsonschema.Draft202012Validator.check_schema

    def checked(cls, schema):
        count.append(schema)
        return original(schema)

    monkeypatch.setattr(
        jsonschema.Draft202012Validator, "check_schema", classmethod(checked)
    )
    validate_document({"value": "first"}, "cache.schema.json", root=tmp_path)
    with pytest.raises(ContractError):
        validate_document({"value": 123}, "cache.schema.json", root=tmp_path)
    validate_document({"value": "third"}, "cache.schema.json", root=tmp_path)
    assert len(count) == 1


def test_changed_same_size_schema_is_revalidated_even_with_old_mtime(tmp_path):
    path = schema_file(tmp_path)
    validate_document({"value": "text"}, path.name, root=tmp_path)
    before = path.stat()
    schema_file(tmp_path, "number")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    with pytest.raises(ContractError):
        validate_document({"value": "text"}, path.name, root=tmp_path)
    validate_document({"value": 123}, path.name, root=tmp_path)
