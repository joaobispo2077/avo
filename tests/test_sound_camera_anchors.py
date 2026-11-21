"""Selected accents bind real camera nodes, never a proposal's claimed transform."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo import capabilities
from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.camera import make_camera_treatment
from avo.timeline.contracts import content_hash, validate_document
from avo.timeline.sound_planning import SoundPlanningError, derive_sound_opportunities
from tests.test_camera_evaluator import geometry
from tests.test_sound_opportunities import intent, plan
from tests.test_sound_opportunities import workspace as opportunity_workspace

workspace = pytest.fixture(name="workspace")(opportunity_workspace.__wrapped__)


def camera_context():
    wrapper = make_camera_treatment(
        "punch-settle",
        target_layer_id="presenter",
        source_id="raw-camera",
        source_sha256="a" * 64,
        geometry=geometry(),
        options=resolve_editing_craft_selection(
            invocation={"camera": {"enabled": True}}
        ),
    )
    anchor = {
        "componentId": "comparison-card",
        "pathHash": content_hash(
            {"behavior": wrapper["camera"], "geometry": wrapper["sourceGeometry"]}
        ),
        "sourceSha256": wrapper["sourceSha256"],
        "nodeIndex": 1,
    }
    animation = {
        "components": [
            {"componentId": "comparison-card", "extensions": {"editingCraft": wrapper}}
        ]
    }
    value = intent(kind="camera-emphasis", cameraAnchor=anchor)
    value.pop("phase")
    return animation, value


def test_camera_node_uses_its_absolute_cue_frame_and_preserves_all_inputs(
    workspace, monkeypatch
):
    snapshot = plan(workspace, monkeypatch)
    animation, selected = camera_context()
    original = deepcopy((snapshot, animation, selected))
    (record,) = derive_sound_opportunities(
        snapshot,
        [selected],
        frame_rate=Fraction(24),
        program_end_frame=72,
        animation=animation,
    )
    # The punch peaks at 0.25 of frames24..35: nearest output frame27.
    assert record["opportunity"]["programFrame"] == 27
    assert record["opportunity"]["cameraAnchor"] == selected["cameraAnchor"]
    assert record["recommendation"] == "audition" and record["silenceAllowed"] is True
    assert (snapshot, animation, selected) == original


@pytest.mark.parametrize(
    "change", ["path", "source", "index", "component", "layer", "missing", "duplicate"]
)
def test_changed_or_unavailable_camera_context_stays_unresolved(
    workspace, monkeypatch, change
):
    snapshot = plan(workspace, monkeypatch)
    animation, selected = camera_context()
    if change == "path":
        selected["cameraAnchor"]["pathHash"] = "0" * 64
    elif change == "source":
        selected["cameraAnchor"]["sourceSha256"] = "0" * 64
    elif change == "index":
        selected["cameraAnchor"]["nodeIndex"] = 255
    elif change == "component":
        selected["cameraAnchor"]["componentId"] = "another"
    elif change == "layer":
        animation["components"][0]["extensions"]["editingCraft"]["camera"][
            "targetLayerId"
        ] = "another"
    elif change == "missing":
        animation = None
    else:
        animation["components"].append(deepcopy(animation["components"][0]))
    (record,) = derive_sound_opportunities(
        snapshot,
        [selected],
        frame_rate=Fraction(24),
        program_end_frame=72,
        animation=animation,
    )
    assert record["opportunity"] is None
    assert record["recommendation"] == "unresolved" and record["issues"]


def test_camera_claim_in_a_proposal_cannot_replace_canonical_context(
    workspace, monkeypatch
):
    animation, selected = camera_context()
    snapshot = plan(workspace, monkeypatch)
    snapshot["items"][0]["camera"] = {
        "state": "authored",
        "pathHash": selected["cameraAnchor"]["pathHash"],
        "during": {
            "nodes": animation["components"][0]["extensions"]["editingCraft"]["camera"][
                "nodes"
            ]
        },
    }
    (record,) = derive_sound_opportunities(
        snapshot, [selected], frame_rate=Fraction(24), program_end_frame=72
    )
    assert record["opportunity"] is None and record["recommendation"] == "unresolved"


@pytest.mark.parametrize("change", ["phase", "kind", "negative-index"])
def test_conflicting_or_malformed_camera_intents_fail_before_derivation(
    workspace, monkeypatch, change
):
    animation, selected = camera_context()
    snapshot = plan(workspace, monkeypatch)
    if change == "phase":
        selected["phase"] = 0.5
    elif change == "kind":
        selected["kind"] = "reveal"
    else:
        selected["cameraAnchor"]["nodeIndex"] = -1
    with pytest.raises(SoundPlanningError):
        derive_sound_opportunities(
            snapshot,
            [selected],
            frame_rate=Fraction(24),
            program_end_frame=72,
            animation=animation,
        )


def test_camera_anchor_implementation_changes_invalidate_native_producer_identity(
    monkeypatch,
):
    from pathlib import Path

    path = Path(capabilities.__file__).parent / "timeline" / "sound_anchors.py"
    original = Path.read_bytes
    before = capabilities._implementation_digest("mix", "ffmpeg.mix")

    def changed(file):
        result = original(file)
        return (
            result + b"\n# changed camera anchor implementation\n"
            if file == path
            else result
        )

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert capabilities._implementation_digest("mix", "ffmpeg.mix") != before


def test_frozen_camera_opportunity_cannot_change_to_an_unrelated_kind(
    workspace, monkeypatch
):
    animation, selected = camera_context()
    (record,) = derive_sound_opportunities(
        plan(workspace, monkeypatch),
        [selected],
        frame_rate=Fraction(24),
        program_end_frame=72,
        animation=animation,
    )
    record["opportunity"]["kind"] = "click"
    with pytest.raises(ValueError):
        validate_document(
            record["opportunity"], "avo.sound-selection.schema.json#/$defs/opportunity"
        )
