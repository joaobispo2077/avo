"""Cutting persists completeness evidence without making a transcript/cut choice."""

from copy import deepcopy
from pathlib import Path

from avo.timeline.contracts import file_fingerprint, validate_document
from tests.test_cutting_service import fixture_service


class GapAnalysis:
    def analyze(self, source, **request):
        return {
            "sourceRef": {
                "locator": str(source),
                "sha256": request["fingerprint"]["sha256"],
            },
            "routing": deepcopy(request["selection"]),
            "syncRef": deepcopy(request["sync_ref"]),
            "preprocessing": {"sourceRange": deepcopy(request["source_range"])},
            "status": "pass",
            "coverage": {"observed": True, "start": 0, "end": 1},
            "words": [
                {
                    "text": "first",
                    "start": 0,
                    "end": 0.25,
                    "alignmentStatus": "aligned",
                },
                {"text": "last", "start": 0.75, "end": 1, "alignmentStatus": "aligned"},
            ],
            "vad": [
                {"start": 0, "end": 0.25},
                {"start": 0.375, "end": 0.625},
                {"start": 0.75, "end": 1},
            ],
            "alignment": {"status": "pass", "characters": []},
            "tools": [{"modelId": "declared-source-analysis-fixture"}],
            "pauseCandidates": [],
        }


def test_source_analysis_saves_bound_coverage_and_returns_a_compact_review_link(
    tmp_path,
):
    service, cmap = fixture_service(tmp_path, analysis_port=GapAnalysis())
    source = cmap["snapshot"]["sources"][0]
    original_source = file_fingerprint(source["locator"])
    result = service.analyze()
    (shown,) = result["coverage"]["speech"]
    assert shown["sourceId"] == source["sourceId"]
    assert shown["status"] == "needs-review" and shown["protectedRangeCount"] == 1
    saved = service.store.load_document(shown["analysisRef"])["payload"][
        "speechCoverage"
    ]
    validate_document(saved, "avo.preparation.schema.json#/$defs/coverage")
    assert shown["coverageHash"] == saved["coverageHash"]
    assert saved["binding"]["sourceRef"]["sha256"] == source["fingerprint"]["sha256"]
    assert saved["protectedRanges"][0]["startTicks"] == 18000
    assert saved["protectedRanges"][0]["endTicksExclusive"] == 30000
    assert saved["authorization"] == "none"
    assert service.workspace.store("cmap").head_hash() == cmap["contentHash"]
    assert file_fingerprint(source["locator"]) == original_source
    assert service.status(result["proposalRef"])["proposal"]["edits"] == []


def test_missing_analysis_remains_unavailable_in_the_persisted_review(tmp_path):
    service, cmap = fixture_service(tmp_path)
    result = service.analyze()
    (shown,) = result["coverage"]["speech"]
    assert shown["status"] == "unavailable"
    saved = service.store.load_document(shown["analysisRef"])["payload"][
        "speechCoverage"
    ]
    assert saved["protectedRanges"] == [saved["binding"]["sourceRange"]]
    assert service.workspace.store("cmap").head_hash() == cmap["contentHash"]


def test_cutting_producer_identity_includes_coverage_code_and_contract(tmp_path):
    service, _ = fixture_service(tmp_path)
    files = {
        Path(key).as_posix(): value
        for key, value in service._implementation_binding()["files"].items()
    }
    assert {
        "src/avo/timeline/preparation.py",
        "schemas/avo.preparation.schema.json",
    } <= files.keys()
