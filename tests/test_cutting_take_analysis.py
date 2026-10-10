from avo.adapters.understand.cutting_semantics import CuttingSemanticsAdapter
from avo.adapters.understand.cutting_take_analysis import CuttingTakeAnalysisAdapter


def test_missing_understand_pin_keeps_retake_reviewable_without_calling_watch():
    class Watch:
        def review_original_takes(self, *args, **kwargs):
            raise AssertionError("missing runtime must not trigger Watch")

    adapter = CuttingTakeAnalysisAdapter(
        watch=Watch(),
        raw_dir="raw",
        watch_request={"model_pin": {}, "policy": {"concurrency": 1}},
    )
    result = adapter.analyze_group(
        {"locator": "original.mkv", "fingerprint": {"sha256": "a" * 64}},
        {"attempts": []},
        {"sourceRef": {"sha256": "a" * 64}},
    )
    assert result["status"] == "needs-review"
    assert result["verifiedAttempts"] == []


def test_watch_tool_failure_preserves_unknown_retake_evidence():
    from avo.timeline.ports import ToolError

    class Watch:
        def review_original_takes(self, *args, **kwargs):
            raise ToolError("WATCH_UNAVAILABLE", "prepared endpoint unavailable")

    adapter = CuttingTakeAnalysisAdapter(
        watch=Watch(),
        raw_dir="raw",
        watch_request={"model_pin": {"id": "configured"}, "policy": {"concurrency": 1}},
    )
    result = adapter.analyze_group(
        {"locator": "original.mkv", "fingerprint": {"sha256": "a" * 64}},
        {"attempts": []},
        {"sourceRef": {"sha256": "a" * 64}},
    )
    assert result["status"] == "needs-review"
    assert result["semanticEquivalence"] is None
    assert result["verifiedAttempts"] == []


def test_semantic_model_cannot_supply_acoustic_authorization():
    semantics = CuttingSemanticsAdapter(
        lambda request: {
            "modelIdentity": {"model": "configured"},
            "response": {"equivalent": True, "protectedDifferences": []},
        }
    )
    adapter = CuttingTakeAnalysisAdapter(semantics=semantics)
    result = adapter.analyze_group(
        {"sourceId": "s"},
        {"attempts": []},
        {"sourceRef": {"sha256": "a"}, "routing": {"stream": 0}},
    )
    assert result["semanticEquivalence"] is True
    assert result["status"] == "needs-review"
    assert result["verifiedAttempts"] == []
    assert result["perTake"] == {}


def test_configured_watch_semantics_reuses_one_bound_visual_call():
    class Watch:
        calls = 0

        def review_original_takes(self, source, **request):
            self.calls += 1
            assert "takeSemantics" in request["context"]
            return {
                "status": "inferred",
                "sourceSha256": "a" * 64,
                "modelIdentity": {"id": "configured"},
                "promptHash": "b" * 64,
                "semanticResponse": {
                    "equivalent": True,
                    "protectedDifferences": [],
                    "reason": "same restart",
                },
                "perTake": {"take": {"visualUsability": 1}},
            }

    watch = Watch()
    adapter = CuttingTakeAnalysisAdapter(
        watch=watch,
        raw_dir="raw",
        watch_request={"model_pin": {"id": "configured"}, "policy": {"concurrency": 1}},
    )
    result = adapter.analyze_group(
        {"locator": "original.mkv", "fingerprint": {"sha256": "a" * 64}},
        {"attempts": [{"takeId": "take"}]},
        {"sourceRef": {"locator": "original.mkv", "sha256": "a" * 64}},
    )
    assert watch.calls == 1
    assert result["semanticEquivalence"] is True
    assert result["status"] == "needs-review"
    assert result["perTake"]["take"].get("acousticComplete") is None
