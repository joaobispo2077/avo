import pytest

from avo.timeline.contracts import ContractError
from avo.timeline.cutting_requests import validate_cutting_request


def test_strict_analyze_request_accepts_section_mapping_and_full_editorial_unit():
    request = {
        "targetDurationMs": 2400000,
        "segmentSectionIds": {"unit": "intro"},
        "editorialUnits": [
            {
                "unitId": "whole",
                "complete": True,
                "sourceRange": {
                    "sourceId": "s",
                    "startTicks": 10,
                    "endTicksExclusive": 20,
                    "timebase": {"num": 1, "den": 1000},
                },
                "central": True,
                "rationale": "Repeated",
                "redundantTo": "other",
            }
        ],
    }
    assert validate_cutting_request(request) == request


@pytest.mark.parametrize(
    "payload",
    [
        {"targetDurationMs": True},
        {"targetDurationMs": -1},
        {"segmentSectionIds": {"s": False}},
        {"mysteriousCut": True},
        {"editorialUnits": [{"unitId": "u", "complete": "true"}]},
    ],
)
def test_strict_analyze_request_rejects_ambiguous_input(payload):
    with pytest.raises(ContractError):
        validate_cutting_request(payload)
