"""Explicitly disabled Resolve effects stay inert reference evidence."""

import json
from copy import deepcopy

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.import_service import TimelineImportService
from avo.timeline.resolve_effects import collect_inactive
from tests import test_timeline_import_service as fixtures
from tests.test_timeline_import_placed_service import _prepare

project_fixture = pytest.fixture(name="import_project")(
    fixtures.import_project.__wrapped__
)


def test_disabled_sibling_is_evidence_but_does_not_qualify_active_owner():
    disabled = {
        "OTIO_SCHEMA": "Effect.1",
        "effect_name": "Resolve Effect",
        "metadata": {"Resolve_OTIO": {"Effect Name": "Dynamic Zoom", "Enabled": False}},
    }
    active = deepcopy(disabled)
    active["metadata"]["Resolve_OTIO"]["Enabled"] = True
    clip = {"OTIO_SCHEMA": "Clip.2", "effects": [disabled, active]}
    records, owners = collect_inactive(clip, "/clip")
    assert len(records) == 1 and records[0]["pointer"] == "/clip/effects/0"
    assert not owners


@pytest.mark.parametrize("enabled", [False, True, None])
def test_only_explicitly_disabled_effect_is_preserved_without_execution(
    import_project, tmp_path, enabled
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=fixtures._probe
    )
    export = tmp_path / "disabled.otio"
    first = _prepare(service, export, original)
    raw = json.loads(export.read_text())
    raw["tracks"]["children"][0]["children"][1]["effects"] = [
        {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "Resolve Effect",
            "metadata": {
                "Resolve_OTIO": {
                    "Effect Name": "Dynamic Zoom",
                    "Enabled": enabled,
                    "Parameters": [{"Key Frames": {"0": {"Value": 0.8}}}],
                }
            },
        }
    ]
    export.write_text(json.dumps(raw))
    options = deepcopy(first["session"]["options"])
    options["declarations"].update(
        sourceOnly=False, reconstructionMode="declared-treatments"
    )
    prepared = service.prepare(
        export,
        mappings=options["mappings"],
        declarations=options["declarations"],
        actor="fixture",
        reason="Inactive effect qualification",
    )
    result = service.validate(prepared["importId"])
    if enabled is not False:
        assert result["status"] == "blocked"
        return
    assert result["status"] == "awaiting-sync", result.get("findings")
    records = result["proposal"]["snapshot"]["layout"]["inactiveEffects"]
    assert (
        len(records) == 1
        and records[0]["enabled"] is False
        and records[0]["name"] == "Dynamic Zoom"
    )
    effect = next(e for e in result["elements"] if e["schema"] == "Effect.1")
    assert effect["disposition"] == "reference-metadata"
