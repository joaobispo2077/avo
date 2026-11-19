from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.editing_craft_qc import candidate_craft_report
from avo.timeline.review import candidate_identity
from avo.timeline.review_runner import ReviewRunner
from avo.timeline.workspace import TimelineWorkspace
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch


def _stamp(frame):
    return {"ticks": frame, "timebase": {"num": 1001, "den": 30000}}


def _fixture(tmp_path):
    candidate = tmp_path / "proof.mp4"
    candidate.write_bytes(b"encoded proof fixture")
    lock = {name: content_hash(name) for name in ("bmap", "cmap", "tracks")}
    record = {
        "kind": "proof-plan",
        "output": {
            "sha256": candidate_identity(candidate, {}, "review")["sha256"],
            "sizeBytes": candidate.stat().st_size,
        },
        "canonicalInputLock": lock,
        "renderProfile": "review",
    }
    record["materializationHash"] = content_hash(record)
    identity = candidate_identity(
        candidate, {"materialization": record["materializationHash"]}, "review"
    )
    cue = {
        "cueId": "hero-title",
        "kind": "animation",
        "start": _stamp(20),
        "end": _stamp(30),
        "intent": "Introduce the subject",
        "targetLayerId": "titles",
        "animation": {"lifecycle": {"entrance": "Fade in", "hold": "Read the name"}},
    }
    store = Mock()
    store.load_index.return_value = {"headRevisionId": "bmap-r0001"}
    store.revision.return_value = {
        "contentHash": lock["bmap"],
        "snapshot": {"cues": [cue]},
    }
    workspace = Mock(spec=TimelineWorkspace)
    workspace.active_dependency_snapshot.side_effect = lambda: dict(lock)
    workspace.store.return_value = store
    coverage = {
        "sampling": "native-frames",
        "frameRate": {"num": 30000, "den": 1001},
        "observedFrames": [19, 20, 24, 30],
        "decodedFrames": list(range(19, 31)),
        "requestedFrames": list(range(19, 31)),
    }
    return workspace, identity, record, coverage


def _finding(finding_id, category, start, end, cited):
    return {
        "findingId": finding_id,
        "category": category,
        "programRange": {"startFrame": start, "endFrameExclusive": end},
        "evidenceRefs": [
            {"kind": "decoded-frame", "artifactId": f"frame-{frame}"} for frame in cited
        ],
    }


def test_uses_only_cited_actual_frames_in_half_open_cue(tmp_path: Path):
    inputs = _fixture(tmp_path)
    findings = [
        _finding("actual-layout", "layout", 19, 25, [20, 24]),
        _finding("nearby-layout", "caption", 15, 31, [19, 30]),
        _finding("unobserved-layout", "layout", 20, 30, [21]),
        _finding("motion-uncertainty", "continuity", 20, 25, [24]),
    ]
    report = candidate_craft_report(*inputs, findings)
    assert report["candidateIdentityHash"] == inputs[1]["identityHash"]
    assert report["materializationHash"] == inputs[2]["materializationHash"]
    assert report["bmapRevisionHash"] == inputs[2]["canonicalInputLock"]["bmap"]
    cue = report["cues"][0]
    assert cue["cueId"] == "hero-title"
    assert cue["targetLayerId"] == "titles"
    assert cue["lifecycle"]["hold"] == "Read the name"
    assert cue["programFrames"] == {"startFrame": 20, "endFrameExclusive": 30}
    assert cue["observedFrames"] == [20, 24]
    assert cue["frameFindings"] == [
        {"findingId": "actual-layout", "observedFrames": [20, 24]},
        {"findingId": "motion-uncertainty", "observedFrames": [24]},
    ]
    assert cue["continuousPlayback"] == "required"
    assert cue["listening"] == "required"
    assert "alpha-compositing" in cue["frameChecks"]
    assert "source-caption-safe-regions" in cue["frameChecks"]
    assert cue["start"] == _stamp(20)


@pytest.mark.parametrize(
    "mismatch",
    ["candidate", "materialization", "profile", "active-track", "bmap-revision"],
)
def test_stale_evidence_cannot_attach(tmp_path, mismatch):
    workspace, identity, record, coverage = _fixture(tmp_path)
    if mismatch == "candidate":
        identity["sha256"] = "f" * 64
    elif mismatch == "materialization":
        record["unsealedField"] = True
    elif mismatch == "profile":
        identity["renderProfile"] = "other"
    elif mismatch == "active-track":
        lock = dict(record["canonicalInputLock"])
        workspace.active_dependency_snapshot.side_effect = None
        workspace.active_dependency_snapshot.return_value = {**lock, "tracks": "f" * 64}
    else:
        workspace.store.return_value.revision.return_value["contentHash"] = "f" * 64
    assert candidate_craft_report(workspace, identity, record, coverage, []) is None


@pytest.mark.parametrize("sampling", ["native-frames", "proxy", ""])
def test_declared_windows_never_substitute_for_observed_frames(tmp_path, sampling):
    workspace, identity, record, coverage = _fixture(tmp_path)
    coverage = deepcopy(coverage)
    coverage.update(
        {
            "sampling": sampling,
            "observedFrames": [] if sampling == "native-frames" else [20, 24],
            "observedWindows": [{"startFrame": 20, "endFrameExclusive": 30}],
        }
    )
    report = candidate_craft_report(workspace, identity, record, coverage, [])
    assert report["cues"][0]["observedFrames"] == []
    assert report["cues"][0]["continuousPlayback"] == "required"
    assert report["cues"][0]["listening"] == "required"


def test_sound_cue_needs_listening_even_at_sampled_frames(tmp_path):
    workspace, identity, record, coverage = _fixture(tmp_path)
    cue = workspace.store.return_value.revision.return_value["snapshot"]["cues"][0]
    cue.update(kind="sfx", animation={})
    report = candidate_craft_report(workspace, identity, record, coverage, [])
    row = report["cues"][0]
    assert row["lifecycle"] == {}
    assert row["observedFrames"] == []
    assert row["frameChecks"] == []
    assert row["listeningChecks"] == [
        "dialogue-intelligibility",
        "cue-audibility-and-mix",
    ]
    assert row["listening"] == "required"


def test_overlapping_edit_layers_keep_distinct_checks_and_observations(tmp_path):
    workspace, identity, record, coverage = _fixture(tmp_path)
    cues = workspace.store.return_value.revision.return_value["snapshot"]["cues"]
    lifecycle = cues[0]["animation"]["lifecycle"]
    lifecycle.update(payoff="Reveal the title", exit="Clear before the next scene")
    cues.extend(
        [
            {
                "cueId": "caption",
                "kind": "caption",
                "intent": "Keep the spoken comparison legible",
                "targetLayerId": "captions",
                "start": _stamp(24),
                "end": _stamp(31),
            },
            {
                "cueId": "title-sound",
                "kind": "sfx",
                "intent": "Accent the title without masking dialogue",
                "targetLayerId": "sfx",
                "start": _stamp(24),
                "end": _stamp(31),
            },
        ]
    )
    findings = [
        _finding("alpha-border", "visual-quality", 20, 24, [20]),
        _finding("caption-clipped", "caption", 29, 31, [30]),
        _finding("timing-needs-playback", "continuity", 23, 25, [24]),
    ]
    report = candidate_craft_report(workspace, identity, record, coverage, findings)
    title, caption, sound = report["cues"]
    assert title["lifecycle"]["payoff"] == lifecycle["payoff"]
    assert title["lifecycle"]["exit"] == lifecycle["exit"]
    assert "handoffs" in title["playbackChecks"]
    assert "alpha-compositing" in title["frameChecks"]
    assert [row["findingId"] for row in title["frameFindings"]] == [
        "alpha-border",
        "timing-needs-playback",
    ]
    assert "glyphs-grouping-alignment" in caption["frameChecks"]
    assert "source-caption-safe-regions" in caption["frameChecks"]
    assert "reading-time" in caption["playbackChecks"]
    assert caption["observedFrames"] == [24, 30]
    assert [row["findingId"] for row in caption["frameFindings"]] == [
        "caption-clipped",
        "timing-needs-playback",
    ]
    assert sound["observedFrames"] == sound["frameFindings"] == []
    assert all(
        row["continuousPlayback"] == row["listening"] == "required"
        for row in report["cues"]
    )


@pytest.mark.parametrize("clock_matches", [True, False])
def test_assembly_observations_require_the_render_clock(tmp_path, clock_matches):
    workspace, identity, proof, coverage = _fixture(tmp_path)
    current = {**proof["canonicalInputLock"], "sync-map": content_hash("sync")}
    workspace.active_dependency_snapshot.side_effect = lambda: current
    record = {
        "kind": "assembly",
        "output": proof["output"],
        "renderProfile": proof["renderProfile"],
        "canonicalInputLock": {
            "bmapRevisionHash": current["bmap"],
            "cmapRevisionHash": current["cmap"],
            "tracksRevisionHash": current["tracks"],
            "syncRevisionHash": current["sync-map"],
        },
        "renderContract": {
            "frameRate": coverage["frameRate"]
            if clock_matches
            else {"num": 25, "den": 1}
        },
    }
    record["materializationHash"] = content_hash(record)
    identity = candidate_identity(
        Path(identity["path"]),
        {"materialization": record["materializationHash"]},
        "review",
    )
    report = candidate_craft_report(workspace, identity, record, coverage, [])
    assert report["cues"][0]["observedFrames"] == ([20, 24] if clock_matches else [])
    assert report["cues"][0]["continuousPlayback"] == "required"


@pytest.mark.parametrize("exact", [True, False])
def test_runner_publishes_only_native_identity_bound_craft_review(tmp_path, exact):
    workspace, identity, record, coverage = _fixture(tmp_path)
    workspace.project = {}
    del workspace.review_change_summary

    class Watch(FakeWatch):
        def review(self, candidate, **request):
            result = super().review(candidate, **request)
            result["coverage"].update(coverage)
            result["reviewContext"] = {
                "craftChecks": {"candidateIdentityHash": identity["identityHash"]},
                "channel": "documentary",
            }
            return result

    candidate = Path(identity["path"])
    if not exact:
        candidate.write_bytes(b"another proof")
    result = ReviewRunner(
        review_root=tmp_path / "review",
        transcription=FakeTranscript(),
        watch=Watch(),
        deterministic_qc=FakeQc(),
        workspace=workspace,
        clock=lambda: "2026-09-02T00:00:00Z",
    ).run(
        checkpoint="cut-proof",
        candidate=candidate,
        dependencies={"sync-map": content_hash("sync-map")},
        render_profile="review",
        materialization=record,
    )
    assert result["state"] == "ai-passed", result.get("blocker")
    context = next(item for item in result["evidence"] if item["kind"] == "watch")[
        "reviewContext"
    ]
    assert context["channel"] == "documentary"
    gate = result["approvalGatePath"].read_text(encoding="utf-8")
    if exact:
        assert context["craftChecks"]["cues"][0]["observedFrames"] == [20, 24]
        assert "## Craft review" in gate
        assert "`hero-title` (animation) has 2 sampled frames" in gate
        assert "listen for audibility and masking" in gate
    else:
        assert "craftChecks" not in context
        assert "## Craft review" not in gate
