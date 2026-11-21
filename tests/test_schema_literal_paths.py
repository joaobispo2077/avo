"""Local schema filenames are literal paths, including hashes in sandbox roots."""

import json

import pytest

from avo.timeline.contracts import ContractError, load_schema, validate_document


@pytest.fixture
def literal_schema(tmp_path):
    directory = tmp_path / "#!sandbox.literal" / "schemas#local"
    directory.mkdir(parents=True)
    common = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://avo.local/literal-common.schema.json",
        "$defs": {"positive": {"type": "integer", "minimum": 1}},
    }
    (directory / "common.json").write_text(json.dumps(common), encoding="utf-8")
    schema = {
        "$schema": common["$schema"],
        "$id": "https://avo.local/literal-main.schema.json",
        "type": "object",
        "required": ["count"],
        "properties": {
            "count": {"$ref": common["$id"] + "#/$defs/positive"},
        },
        "$defs": {
            "item": {"$ref": common["$id"] + "#/$defs/positive"},
            "key#with/hash~": {"type": "boolean"},
        },
    }
    path = directory / "main#literal.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    return path


@pytest.mark.parametrize("explicit_root", [False, True])
def test_absolute_literal_hash_path_retains_local_registry(
    literal_schema, explicit_root
):
    kwargs = {"root": literal_schema.parent} if explicit_root else {}
    assert load_schema(str(literal_schema), **kwargs)["type"] == "object"
    assert validate_document({"count": 2}, str(literal_schema), **kwargs) == {
        "count": 2
    }
    with pytest.raises(ContractError, match="minimum"):
        validate_document({"count": 0}, str(literal_schema), **kwargs)


@pytest.mark.parametrize("absolute", [False, True])
def test_fragment_after_literal_hash_path_keeps_uri_refs(literal_schema, absolute):
    name = str(literal_schema) if absolute else literal_schema.name
    kwargs = {} if absolute else {"root": literal_schema.parent}
    reference = name + "#/$defs/item"
    assert validate_document(3, reference, **kwargs) == 3
    with pytest.raises(ContractError, match="integer"):
        validate_document("three", reference, **kwargs)


def test_literal_hash_and_pointer_escaping_are_independent(literal_schema):
    reference = str(literal_schema) + "#/$defs/key#with~1hash~0"
    assert validate_document(True, reference) is True
    with pytest.raises(ContractError, match="boolean"):
        validate_document(1, reference)


def test_relative_schema_and_json_pointer_still_work(tmp_path):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"item": {"type": "string", "minLength": 2}},
    }
    (tmp_path / "plain.json").write_text(json.dumps(schema), encoding="utf-8")
    assert validate_document("ok", "plain.json#/$defs/item", root=tmp_path) == "ok"
    with pytest.raises(ContractError, match="too short"):
        validate_document("x", "plain.json#/$defs/item", root=tmp_path)
