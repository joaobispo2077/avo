import json

from avo.paths import schema_path


def test_brief_keeps_author_summary_separate_from_expanded_option_view():
    schema = json.loads(schema_path("avo.briefstart.schema.json").read_text())
    assert schema["$defs"]["ProjectBriefVersion"]["properties"]["summaryText"] == {
        "type": "string"
    }
