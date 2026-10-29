from avo.timeline.review_runner import select_microproof_windows


def test_selects_declared_historical_and_one_representative_per_operation_kind():
    plan = {
        "validationPlan": {"microproof": [{"startFrame": 0, "endFrameExclusive": 30}]},
        "regressionContract": {
            "historicalRiskWindows": [{"startFrame": 300, "endFrameExclusive": 360}]
        },
        "videoGraph": {
            "operations": [
                {
                    "operationId": "overlay-a",
                    "kind": "overlay-image",
                    "outputRange": {"startFrame": 0, "endFrameExclusive": 30},
                },
                {
                    "operationId": "overlay-b",
                    "kind": "overlay-image",
                    "outputRange": {"startFrame": 90, "endFrameExclusive": 120},
                },
                {
                    "operationId": "card-a",
                    "kind": "text-card-graphic",
                    "outputRange": {"startFrame": 180, "endFrameExclusive": 240},
                },
            ]
        },
    }
    windows = select_microproof_windows(plan)
    assert [(item["startFrame"], item["endFrameExclusive"]) for item in windows] == [
        (0, 30),
        (180, 240),
        (300, 360),
    ]
    assert windows[0]["reasons"] == [
        "declared-microproof",
        "changed-operation:overlay-image",
    ]
    assert windows[1]["operationIds"] == ["card-a"]
    assert windows[2]["reasons"] == ["historical-risk"]


def test_window_selection_is_deterministic_and_rejects_invalid_ranges():
    plan = {
        "validationPlan": {"microproof": []},
        "regressionContract": {"historicalRiskWindows": []},
        "videoGraph": {
            "operations": [
                {
                    "operationId": "bad-op",
                    "kind": "crop",
                    "outputRange": {"startFrame": 10, "endFrameExclusive": 10},
                }
            ]
        },
    }
    import pytest

    with pytest.raises(ValueError, match="half-open"):
        select_microproof_windows(plan)


def test_generated_operations_select_real_program_windows_without_restarting_local_phase():
    from copy import deepcopy

    plan = {
        "validationPlan": {"microproof": [{"startFrame": 20, "endFrameExclusive": 40}]},
        "regressionContract": {"historicalRiskWindows": []},
        "videoGraph": {
            "operations": [
                {
                    "operationId": "base-generated",
                    "kind": "generated-clip",
                    "outputRange": {"startFrame": 0, "endFrameExclusive": 30},
                    "parameters": {
                        "sourceRange": {"startFrame": 7, "endFrameExclusive": 37}
                    },
                },
                {
                    "operationId": "cross-cut-overlay",
                    "kind": "overlay-video",
                    "outputRange": {"startFrame": 10, "endFrameExclusive": 50},
                    "parameters": {
                        "sourceRange": {"startFrame": 9, "endFrameExclusive": 49}
                    },
                },
            ]
        },
    }
    original = deepcopy(plan)
    windows = select_microproof_windows(plan)
    assert [(row["startFrame"], row["endFrameExclusive"]) for row in windows] == [
        (0, 30),
        (10, 50),
        (20, 40),
    ]
    assert windows[1]["operationIds"] == ["cross-cut-overlay"]
    assert plan == original
    parameters = plan["videoGraph"]["operations"][1]
    assert (
        parameters["parameters"]["sourceRange"]["startFrame"]
        + 20
        - parameters["outputRange"]["startFrame"]
        == 19
    )
