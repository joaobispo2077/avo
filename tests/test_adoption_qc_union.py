import pytest

from avo.adapters.qc.registry import CheckpointQcRegistry
from avo.timeline.review import CHECKPOINT_POLICIES


def test_adoption_keeps_each_required_native_evidence_kind():
    required = set().union(
        *(
            CHECKPOINT_POLICIES[name]["required"]
            for name in ("motion-proof", "pre-master", "deliver")
        )
    )
    evidence = [
        {"kind": kind, "status": "pass", "findings": []} for kind in sorted(required)
    ]
    normal = CheckpointQcRegistry._filtered_result({}, "deliver", evidence, [])
    adoption = CheckpointQcRegistry._filtered_result(
        {}, "deliver", evidence, [], adoption=True
    )
    assert {item["kind"] for item in normal["evidence"]} == CHECKPOINT_POLICIES[
        "deliver"
    ]["required"]
    assert {item["kind"] for item in adoption["evidence"]} == required


def test_adoption_retains_failed_motion_dependency():
    result = CheckpointQcRegistry._filtered_result(
        {},
        "deliver",
        [
            {
                "kind": "animation",
                "status": "fail",
                "findings": [{"id": "stale-animation"}],
            }
        ],
        [],
        adoption=True,
    )
    assert result["status"] == "fail"
    assert result["findings"] == [{"id": "stale-animation"}]


def test_adoption_requires_final_file_checkpoint(tmp_path):
    with pytest.raises(ValueError, match="deliver checkpoint"):
        CheckpointQcRegistry(adoption=True).check(
            tmp_path / "unused.mp4", checkpoint="cut-proof"
        )
