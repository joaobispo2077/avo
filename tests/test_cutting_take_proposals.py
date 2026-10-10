from avo.timeline.contracts import content_hash
from avo.timeline.cutting_policy import resolve_cutting_policy
from avo.timeline.cutting_take_proposals import discover_retake_groups, propose_retakes


def materials():
    interval = {
        "sourceId": "s",
        "startTicks": 0,
        "endTicksExclusive": 4000,
        "timebase": {"num": 1, "den": 1000},
    }
    segment = {
        "segmentId": "seg",
        "sourceId": "s",
        "in": {"ticks": 0, "timebase": interval["timebase"]},
        "out": {"ticks": 4000, "timebase": interval["timebase"]},
    }
    source = {
        "sourceId": "s",
        "locator": "original.mkv",
        "fingerprint": {"sha256": "a" * 64},
    }
    analysis = {
        "sourceRef": {"locator": "original.mkv", "sha256": "a" * 64},
        "syncRef": {"locator": "sync.json", "sha256": "b" * 64},
        "routing": {"streamIndex": 1},
        "preprocessing": {"sourceRange": interval},
        "status": "pass",
        "words": [
            {"text": "Uma", "start": 0.2, "end": 0.4},
            {"text": "Uma", "start": 1.0, "end": 1.2},
            {"text": "das", "start": 1.2, "end": 1.3},
            {"text": "coisas.", "start": 1.4, "end": 2.2},
        ],
    }
    return {"sources": [source], "segments": [segment]}, analysis


class VerifiedPort:
    def analyze_group(self, source, group, analysis, **request):
        attempts = [dict(take) for take in group["attempts"]]
        attempts[0].update(complete=False, abandoned=True)
        attempts[1].update(complete=True)
        return {
            "sourceRef": analysis["sourceRef"],
            "syncRef": analysis["syncRef"],
            "routing": analysis["routing"],
            "groupHash": content_hash(group),
            "status": "corroborated",
            "verifiedAttempts": attempts,
            "semanticEquivalence": True,
            "restartConfirmed": True,
            "evidenceRefs": [request["analysis_ref"]],
            "perTake": {
                take["takeId"]: {
                    "acousticComplete": True,
                    "intelligible": True,
                    "intelligibility": 0.9,
                    "cadence": 0.8,
                    "visualUsability": 0.8,
                }
                for take in attempts
            },
        }


def test_asr_candidate_discovery_needs_no_handcrafted_group_but_does_not_certify():
    snapshot, analysis = materials()
    groups = discover_retake_groups(analysis, snapshot["segments"][0])
    assert len(groups) == 1
    assert all(take["complete"] is None for take in groups[0]["attempts"])
    occurrences, edits = propose_retakes(snapshot, {"seg": analysis})
    assert occurrences[0]["disposition"] == "needs-review"
    assert edits == []


def test_verified_retake_proposal_removes_only_whole_rejected_unit():
    snapshot, analysis = materials()
    occurrences, edits = propose_retakes(
        snapshot,
        {"seg": analysis},
        analysis_refs={"seg": {"locator": "analysis.json", "sha256": "c" * 64}},
        evidence_port=VerifiedPort(),
    )
    assert occurrences[0]["disposition"] == "replace"
    assert len(edits) == 1
    assert edits[0]["removeRange"]["startTicks"] == 200
    assert edits[0]["removeRange"]["endTicksExclusive"] == 400
    assert edits[0]["segmentId"] == "seg"


def test_protected_rejected_take_cannot_be_removed():
    snapshot, analysis = materials()
    policy = resolve_cutting_policy(
        project_settings={"enabled": True, "family": "analysis-review"},
        protected_events=[
            {
                "eventId": "locked",
                "sourceRange": {
                    "sourceId": "s",
                    "startTicks": 200,
                    "endTicksExclusive": 400,
                    "timebase": {"num": 1, "den": 1000},
                },
            }
        ],
    )
    occurrences, edits = propose_retakes(
        snapshot,
        {"seg": analysis},
        analysis_refs={"seg": {"locator": "analysis.json", "sha256": "c" * 64}},
        evidence_port=VerifiedPort(),
        policy=policy,
    )
    assert edits == []
    assert "locked" in occurrences[0]["protections"]


def test_unbound_or_changed_source_evidence_cannot_apply():
    snapshot, analysis = materials()
    analysis["sourceRef"]["sha256"] = "d" * 64
    occurrences, edits = propose_retakes(
        snapshot,
        {"seg": analysis},
        analysis_refs={"seg": {"locator": "analysis.json", "sha256": "c" * 64}},
        evidence_port=VerifiedPort(),
    )
    assert edits == []
    assert occurrences[0]["disposition"] == "needs-review"


def test_timing_refinement_does_not_reset_retake_identity():
    snapshot, analysis = materials()
    before = discover_retake_groups(analysis, snapshot["segments"][0])[0]["groupId"]
    analysis["words"][0].update(start=0.21, end=0.41)
    after = discover_retake_groups(analysis, snapshot["segments"][0])[0]["groupId"]
    assert before == after
