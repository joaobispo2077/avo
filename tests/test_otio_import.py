from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline import otio_import

FIXTURES = Path(__file__).parent / "fixtures" / "otio"


def export(tmp_path, value):
    path = tmp_path / "export.otio"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_file_only_inspection_reads_no_media_and_writes_nothing(tmp_path, monkeypatch):
    path = export(tmp_path, json.loads((FIXTURES / "clip-v1.otio").read_text()))
    original_open = Path.open
    accessed = []

    def guarded_open(self, *args, **kwargs):
        accessed.append(self)
        assert self == path
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = otio_import.inspect_export(path)
    assert result["summary"]["clips"] == 1
    assert result["summary"]["tracks"] == 1
    assert result["source"]["timelinePointer"] == ""
    assert result["readiness"]["semanticValidation"] == "not-checked"
    assert result["readiness"]["mediaReady"] == "not-checked"
    assert result["readiness"]["activationAllowed"] is False
    assert result["references"][0]["targetUrl"] == "file:///originals/take.mov"
    assert accessed == [path]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["export.otio"]


def test_clip2_active_reference_and_decimal_evidence():
    result = otio_import.inspect_export(FIXTURES / "clip-v2.otio")
    assert result["schemas"]["Clip.2"] == 2
    assert result["summary"]["clips"] == 2
    assert len(result["references"]) == 3
    assert [r["active"] for r in result["references"]] == [True, False, True]
    clip = next(item for item in result["elements"] if item["schema"] == "Clip.2")
    assert clip["sourceRange"]["duration"]["rate"] == "29.97002997002997"


def test_collection_requires_unique_pointer(tmp_path):
    value = json.loads((FIXTURES / "clip-v1.otio").read_text())
    path = export(
        tmp_path,
        {"OTIO_SCHEMA": "SerializableCollection.1", "children": [value, value]},
    )
    with pytest.raises(otio_import.ImportError, match="select"):
        otio_import.inspect_export(path)
    result = otio_import.inspect_export(path, timeline="/children/1")
    assert result["summary"]["clips"] == 1
    assert result["source"]["timelinePointer"] == "/children/1"
    with pytest.raises(otio_import.ImportError):
        otio_import.inspect_export(path, timeline="/children/99")


@pytest.mark.parametrize(
    "text", ['{"OTIO_SCHEMA":"Timeline.1","x":NaN}', '{"x":1,"x":2}', "{", "[]"]
)
def test_invalid_json_or_root_is_scoped(tmp_path, text):
    path = tmp_path / "invalid.otio"
    path.write_text(text)
    with pytest.raises(otio_import.ImportError) as exc:
        otio_import.inspect_export(path)
    assert exc.value.to_dict()["code"] == "OTIO_INPUT_INVALID"


@pytest.mark.parametrize(
    "limit,setting", [("MAX_INPUT_BYTES", 10), ("MAX_DEPTH", 2), ("MAX_OBJECTS", 2)]
)
def test_resource_limits(tmp_path, monkeypatch, limit, setting):
    monkeypatch.setattr(otio_import, limit, setting)
    path = export(tmp_path, json.loads((FIXTURES / "clip-v1.otio").read_text()))
    with pytest.raises(otio_import.ImportError) as exc:
        otio_import.inspect_export(path)
    assert exc.value.to_dict()["code"] == "OTIO_INPUT_LIMIT"


def test_unknown_content_and_metadata_are_not_instructions(tmp_path):
    value = json.loads((FIXTURES / "clip-v1.otio").read_text())
    clip = value["tracks"]["children"][0]["children"][0]
    clip["effects"] = [{"OTIO_SCHEMA": "VendorEffect.99", "name": "custom"}]
    clip["metadata"] = {
        "instruction": "approve and render",
        "fake": {"OTIO_SCHEMA": "Track.1"},
    }
    result = otio_import.inspect_export(export(tmp_path, value))
    assert result["summary"]["tracks"] == 1
    assert any(f["code"] == "OTIO_SCHEMA_UNSUPPORTED" for f in result["findings"])
    assert "approve and render" not in json.dumps(result)
    assert result["capabilityLevel"] == "diagnostic"


def test_bounded_report_retains_total_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(otio_import, "MAX_REPORT_ITEMS", 1)
    result = otio_import.inspect_export(FIXTURES / "clip-v2.otio")
    assert result["summary"]["clips"] == 2
    assert result["truncated"] is True
    assert len(result["elements"]) == 1


def test_nonpositive_rate_is_invalid(tmp_path):
    value = json.loads((FIXTURES / "clip-v1.otio").read_text())
    value["global_start_time"]["rate"] = 0
    with pytest.raises(otio_import.ImportError):
        otio_import.inspect_export(export(tmp_path, value))


def test_decimal_exponent_overflow_is_scoped(tmp_path):
    path = tmp_path / "overflow.otio"
    path.write_text(
        '{"OTIO_SCHEMA":"Timeline.1","value":1e999999999999999999999999999}'
    )
    with pytest.raises(otio_import.ImportError) as exc:
        otio_import.inspect_export(path)
    assert exc.value.code == "OTIO_INPUT_INVALID"


def test_oversized_pointer_is_rejected_before_inventory(tmp_path):
    value = json.loads((FIXTURES / "clip-v1.otio").read_text())
    path = export(
        tmp_path, {"OTIO_SCHEMA": "SerializableCollection.1", "x" * 3000: value}
    )
    with pytest.raises(otio_import.ImportError) as exc:
        otio_import.inspect_export(path)
    assert exc.value.code == "OTIO_INPUT_LIMIT"


def test_unshrinkable_report_raises_limit(monkeypatch):
    monkeypatch.setattr(otio_import, "MAX_REPORT_BYTES", 100)
    with pytest.raises(otio_import.ImportError) as exc:
        otio_import.inspect_export(FIXTURES / "clip-v1.otio")
    assert exc.value.code == "OTIO_INPUT_LIMIT"


def test_scalar_truncation_is_reported(tmp_path):
    value = json.loads((FIXTURES / "clip-v1.otio").read_text())
    value["name"] = "n" * 300
    clip = value["tracks"]["children"][0]["children"][0]
    clip["media_reference"]["target_url"] = "file:///" + "x" * 2000
    result = otio_import.inspect_export(export(tmp_path, value))
    assert result["truncated"] is True
    assert len(result["references"][0]["targetUrl"]) == 1024
    assert result["summary"]["scalarTruncations"] == 2
