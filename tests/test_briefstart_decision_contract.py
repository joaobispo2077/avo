import json

from avo.paths import schema_path


def test_project_decision_preserves_typed_project_edits_without_provider_fields():
    schema = json.loads(schema_path("avo.briefstart.schema.json").read_text())
    decision = schema["$defs"]["CreatorDecision"]["properties"]
    edits = schema["$defs"]["BriefDecideRequest"]["properties"]["edits"]
    assert decision["edits"] == edits
    assert decision["scope"] == {"const": "project"}
