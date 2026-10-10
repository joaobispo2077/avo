import pytest

from avo.timeline.cutting_previews import group_preview_windows


def test_opted_in_clock_half_tie_uses_native_half_up_and_legacy_stays_even():
    from fractions import Fraction

    from avo.timeline.initial_cut import _clock_boundary

    assert _clock_boundary(Fraction(1, 2), False) == 0
    assert _clock_boundary(Fraction(1, 2), True) == 1


def test_removed_take_occurrence_maps_to_source_switch_join():
    from avo.adapters.media.cutting_preview import _assign_edit_windows

    def interval(source, first, last):
        return {
            "sourceId": source,
            "startTicks": first,
            "endTicksExclusive": last,
            "timebase": {"num": 1, "den": 1000},
        }

    joins = [
        {
            "leftSourceRange": interval("old", 0, 500),
            "rightSourceRange": interval("replacement", 0, 500),
        }
    ]
    windows = [{"occurrenceIds": ["join-one"]}]
    _assign_edit_windows(
        windows,
        joins,
        [{"occurrenceId": "take-one", "removeRange": interval("old", 500, 1000)}],
    )
    assert windows[0]["occurrenceIds"] == ["join-one", "take-one"]


def test_native_factory_supplies_pipeline_verifier_only_when_cutting_required(tmp_path):
    from types import SimpleNamespace

    from avo.adapters.media.cutting_preview import CuttingPreviewAdapter
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    native = TimelineRenderAdapter(proof_executor=object())
    workspace = SimpleNamespace(timeline_dir=tmp_path)
    assert native.for_proof_plan(workspace, {"validationPlan": {}}) is native
    port = native.for_proof_plan(
        workspace, {"validationPlan": {"cutting": {"required": True}}}
    )
    assert isinstance(port, CuttingPreviewAdapter)
    assert port.render_port is native
    assert callable(port.verify_cutting_window)


def test_observed_word_crossing_source_cut_is_not_silently_dropped():
    from avo.adapters.media.cutting_preview import (
        CuttingPreviewAdapter,
        CuttingWordBoundaryError,
    )

    mapping = {
        "sourceRange": {
            "sourceId": "one",
            "startTicks": 500,
            "endTicksExclusive": 1000,
            "timebase": {"num": 1, "den": 1000},
        },
        "fingerprint": {"sha256": "a" * 64},
        "selection": {"streamIndex": 0},
        "localStartSeconds": 0,
    }
    analysis = {
        "sourceRef": {"sha256": "a" * 64},
        "routing": {"streamIndex": 0},
        "words": [{"text": "complete", "start": 0.4, "end": 0.7, "eligibleEdge": True}],
    }
    with pytest.raises(
        CuttingWordBoundaryError, match="crosses selected source boundary"
    ):
        CuttingPreviewAdapter._mapped_words(mapping, [analysis])


def test_partial_word_blocks_window_basis_even_if_reference_recipe_matches(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo.adapters.media.cutting_preview import (
        CuttingPreviewAdapter,
        CuttingWordBoundaryError,
    )

    adapter = CuttingPreviewAdapter(
        SimpleNamespace(timeline_dir=tmp_path), render_port=object(), verifier=object()
    )

    def collision(*args):
        raise CuttingWordBoundaryError("word chopped at the source cut")

    monkeypatch.setattr(adapter, "_observed_words", collision)
    windows = adapter._verification_windows(
        {"window": {"occurrenceIds": ["join-one"]}},
        [],
        {"proposal": {}, "snapshot": {}},
    )
    assert windows[0]["retainedWordEdges"] == []


def test_context_window_outer_edge_does_not_misclassify_a_whole_source_word():
    from avo.adapters.media.cutting_preview import CuttingPreviewAdapter

    selected = {
        "sourceId": "one",
        "startTicks": 0,
        "endTicksExclusive": 1000,
        "timebase": {"num": 1, "den": 1000},
    }
    mapping = {
        "sourceRange": {**selected, "startTicks": 500},
        "fullNodeSourceRange": selected,
        "fingerprint": {"sha256": "a" * 64},
        "selection": {"streamIndex": 0},
        "localStartSeconds": 0,
    }
    analysis = {
        "sourceRef": {"sha256": "a" * 64},
        "routing": {"streamIndex": 0},
        "words": [
            {"text": "context", "start": 0.4, "end": 0.7, "eligibleEdge": True},
            {"text": "retained", "start": 0.8, "end": 0.9, "eligibleEdge": True},
        ],
    }
    words = CuttingPreviewAdapter._mapped_words(mapping, [analysis])
    assert [word["text"] for word in words] == ["retained"]


def test_complete_selected_long_attempt_expands_indivisible_native_preview():
    from avo.adapters.media.cutting_preview import _group_windows

    interval = {
        "sourceId": "one",
        "startTicks": 10000,
        "endTicksExclusive": 230000,
        "timebase": {"num": 1, "den": 1000},
    }
    request = {
        "output": {"frameRate": {"num": 30, "den": 1}},
        "videoGraph": {
            "operations": [
                {
                    "kind": "trim",
                    "outputRange": {"startFrame": 0, "endFrameExclusive": 6600},
                    "parameters": {
                        "sourceId": "one",
                        "sourceRange": {
                            "startTicks": 10000,
                            "endTicks": 230000,
                            "timebase": {"num": 1, "den": 1000},
                        },
                    },
                }
            ]
        },
        "validationPlan": {"microproof": []},
    }
    occurrence = {
        "occurrenceId": "retake-one",
        "sourceRange": interval,
        "selectedAlternativeId": "take-two",
        "alternatives": [{"takeId": "take-two", "sourceRange": interval}],
    }
    result = _group_windows(
        request,
        [],
        [occurrence],
        [
            {
                "occurrenceId": "retake-one",
                "removeRange": {
                    **interval,
                    "startTicks": 0,
                    "endTicksExclusive": 10000,
                },
            }
        ],
    )
    assert result == [
        {"startFrame": 0, "endFrameExclusive": 6600, "occurrenceIds": ["retake-one"]}
    ]


def test_rejected_alternative_reference_does_not_claim_candidate_coverage():
    from avo.adapters.media.cutting_preview import _alternative_review_refs

    interval = {
        "sourceId": "one",
        "startTicks": 10,
        "endTicksExclusive": 20,
        "timebase": {"num": 1, "den": 1000},
    }
    reference = {"locator": "analysis.json", "sha256": "b" * 64}
    records = _alternative_review_refs(
        {
            "sources": [
                {
                    "sourceId": "one",
                    "locator": "original.mkv",
                    "fingerprint": {"sha256": "a" * 64},
                }
            ]
        },
        {
            "occurrences": [
                {
                    "occurrenceId": "retake",
                    "alternatives": [{"takeId": "rejected", "sourceRange": interval}],
                    "evidenceRefs": [reference],
                }
            ]
        },
    )
    assert records[0]["sourceRef"] == {"locator": "original.mkv", "sha256": "a" * 64}
    assert records[0]["sourceRange"] == interval
    assert records[0]["evidenceRefs"] == [reference]
    assert "not encoded candidate coverage" in records[0]["claimScope"]


def test_nearby_windows_group_with_context_and_all_case_identities():
    result = group_preview_windows(
        [
            {"startFrame": 0, "endFrameExclusive": 600, "occurrenceIds": ["one"]},
            {"startFrame": 1500, "endFrameExclusive": 2100, "occurrenceIds": ["two"]},
        ],
        {"num": 30, "den": 1},
    )
    assert result == [
        {"startFrame": 0, "endFrameExclusive": 2100, "occurrenceIds": ["one", "two"]}
    ]


def test_grouping_splits_between_complete_windows_not_inside_a_case():
    result = group_preview_windows(
        [
            {"startFrame": 0, "endFrameExclusive": 3000, "occurrenceIds": ["one"]},
            {"startFrame": 5000, "endFrameExclusive": 8000, "occurrenceIds": ["two"]},
        ],
        {"num": 30, "den": 1},
    )
    assert len(result) == 2
    assert result[1]["startFrame"] == 5000


def test_long_complete_attempt_is_not_split_to_meet_a_duration_target():
    window = {
        "startFrame": 0,
        "endFrameExclusive": 9000,
        "occurrenceIds": ["complete-take"],
    }
    assert group_preview_windows([window], {"num": 30, "den": 1}) == [window]


def test_invalid_clock_cannot_create_an_empty_preview():
    with pytest.raises(ValueError):
        group_preview_windows(
            [{"startFrame": 10, "endFrameExclusive": 10}], {"num": 30, "den": 1}
        )


def test_preview_plan_cannot_be_promoted_to_full_proof(tmp_path):
    from avo.timeline.materialize import (
        ProofMaterializationError,
        materialize_proof_plan,
    )

    with pytest.raises(ProofMaterializationError, match="preview"):
        materialize_proof_plan(
            workspace=None,
            proof_plan={"previewOnly": True},
            media_inputs={},
            microproof_gate={},
        )


def test_opted_in_microproof_render_success_is_not_speech_verification(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo.timeline import materialize
    from avo.timeline.contracts import file_fingerprint

    plan = {
        "proofPlanId": "proof-plan-test",
        "proofPlanHash": "a" * 64,
        "output": {"path": "proof.mp4"},
        "videoGraph": {"operations": []},
        "regressionContract": {},
        "validationPlan": {
            "microproof": [{"startFrame": 0, "endFrameExclusive": 30}],
            "cutting": {
                "required": True,
                "proposalRef": {"locator": "proposal", "sha256": "b" * 64},
                "graphHash": "c" * 64,
                "joinIds": ["join-one"],
            },
        },
    }
    compiler = SimpleNamespace(
        require_preflight=lambda *args, **kwargs: {"reportHash": "d" * 64}
    )
    monkeypatch.setattr(
        materialize, "_proof_plan_value", lambda *args: (compiler, plan)
    )

    class Renderer:
        def proof_tool_readiness(self, value):
            return {"ffmpeg": True}

        def render_proof_plan(self, value, output, *, window):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"render success is not observed speech")
            return {
                "status": "pass",
                "output": file_fingerprint(output),
                "graphHash": "e" * 64,
            }

    gate = materialize.render_proof_microproofs(
        workspace=SimpleNamespace(timeline_dir=tmp_path),
        proof_plan=plan,
        media_inputs={},
        render_port=Renderer(),
    )
    assert gate["status"] != "pass"
    assert gate["results"][0]["verification"]["status"] == "blocked"


def test_proposed_view_does_not_transfer_prior_cutting_approval():
    from types import SimpleNamespace

    from avo.adapters.media.cutting_preview import _ProposedWorkspace

    original = {
        "cuttingRef": {"locator": "old", "sha256": "a" * 64},
        "protectionRef": {"locator": "old-protection", "sha256": "b" * 64},
        "segments": [],
    }
    workspace = SimpleNamespace(
        store=lambda _: SimpleNamespace(revision=lambda _: {"snapshot": original})
    )
    view = _ProposedWorkspace(workspace, original)
    proposed = view.store("cmap").revision("current")["snapshot"]
    assert "cuttingRef" not in proposed
    assert "protectionRef" not in proposed
    assert "cuttingRef" in original


def test_canonical_request_binds_current_cutting_evidence_not_render_approval(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo.timeline import cutting_store
    from avo.timeline.cutting_contracts import selection_graph_hash
    from avo.timeline.initial_cut import initial_cut_proof_request
    from tests.test_initial_cut_request import workspace

    project, snapshot = workspace(tmp_path)
    project.timeline_dir = tmp_path
    project.video_id = "test"
    project.project = {"provider": "bishop"}
    reference = {"locator": "verification.json", "sha256": "a" * 64}
    proposal = {"locator": "proposal.json", "sha256": "b" * 64}
    snapshot["cuttingRef"] = reference
    snapshot["sources"][0]["kind"] = "raw"
    snapshot["sources"][1]["kind"] = "raw"
    for segment in snapshot["segments"]:
        segment["reason"] = "retain complete source unit"
        for key in ("in", "out"):
            segment[key].update(domain="raw-source", sourceId=segment["sourceId"])
    monkeypatch.setattr(
        cutting_store,
        "CuttingStore",
        lambda *args, **kwargs: SimpleNamespace(
            load_document=lambda ref: {
                "documentType": "verification",
                "payload": {
                    "status": "pass",
                    "proposalRef": proposal,
                    "graphHash": selection_graph_hash(snapshot),
                },
            }
        ),
    )
    request = initial_cut_proof_request(
        project,
        iteration_id="test",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 30, "den": 1},
    )
    binding = request["validationPlan"]["cutting"]
    assert binding["required"] is True
    assert binding["verificationRef"] == reference
    assert binding["proposalRef"] == proposal
    assert len(binding["joinIds"]) == 1


def test_native_window_rechecks_encoded_bytes_and_does_not_reuse_preview_pass(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo.adapters.media import cutting_preview
    from avo.timeline.contracts import file_fingerprint
    from avo.timeline.cutting_contracts import selection_graph_hash

    snapshot = {
        "sources": [],
        "segments": [],
        "cuttingRef": {"locator": "approved-preview"},
    }
    store = SimpleNamespace(
        load_index=lambda: {"headRevisionId": "current"},
        revision=lambda _: {"snapshot": snapshot},
    )
    workspace = SimpleNamespace(
        timeline_dir=tmp_path,
        video_id="test",
        project={"provider": "bishop"},
        store=lambda _: store,
    )
    candidate = tmp_path / "fresh.mp4"
    candidate.write_bytes(b"new encoded bytes")
    proof = tmp_path / "current-plan.json"
    proof.write_text("{}")
    proposal_ref = {"locator": "proposal", "sha256": "a" * 64}
    proposal = {"syncRef": {}, "occurrences": []}
    monkeypatch.setattr(
        cutting_preview,
        "CuttingStore",
        lambda *args, **kwargs: SimpleNamespace(
            load_document=lambda _: {"payload": proposal}
        ),
    )
    monkeypatch.setattr(
        cutting_preview,
        "ProofPlanCompiler",
        lambda _: SimpleNamespace(path=lambda _: proof),
    )
    monkeypatch.setattr(
        cutting_preview,
        "audit_joins",
        lambda *args, **kwargs: [{"joinId": "join-one", "programFrame": 15}],
    )
    calls = []

    class Verifier:
        def verify(self, path, **request):
            calls.append((path, request))
            return {
                "status": "blocked",
                "checks": [{"reason": "word evidence unavailable"}],
            }

    adapter = cutting_preview.CuttingPreviewAdapter(
        workspace, render_port=object(), verifier=Verifier()
    )
    monkeypatch.setattr(adapter, "_clock_maps", lambda *args: [])
    monkeypatch.setattr(adapter, "_verification_windows", lambda *args: [])
    plan = {
        "proofPlanId": "current",
        "proofPlanHash": "b" * 64,
        "output": {"frameRate": {"num": 30, "den": 1}},
        "validationPlan": {
            "cutting": {
                "required": True,
                "proposalRef": proposal_ref,
                "graphHash": selection_graph_hash(snapshot),
            }
        },
    }
    result = adapter.verify_cutting_window(
        plan, candidate, window={"startFrame": 0, "endFrameExclusive": 30}
    )
    assert result["status"] == "blocked"
    assert result["verifiedJoinIds"] == []
    assert result["candidateSha256"] == file_fingerprint(candidate)["sha256"]
    assert calls[0][0] == candidate
    assert calls[0][1]["required_occurrences"] == ["join-one"]
