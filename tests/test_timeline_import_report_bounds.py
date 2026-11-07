"""Display bounds retain authority facts without rewriting durable evidence."""

import json
from copy import deepcopy

from avo.timeline_import_cli import _report_json


def _result():
    return {
        "operation": "activate",
        "status": "active-draft",
        "importId": "a" * 64,
        "validationHash": "b" * 64,
        "readiness": {"activationAllowed": False, "reviewState": "not-started"},
        "source": {"sha256": "c" * 64},
        "target": {"provider": "channel", "videoId": "trial"},
        "session": {"refs": {"proposal": {"path": "proposal.json"}}},
    }


def test_small_reports_keep_their_complete_shape():
    result = _result()
    result["session"]["options"] = {"mediaRoots": ["originals"]}
    assert json.loads(_report_json(result)) == result


def test_successful_activation_compacts_snapshots_and_keeps_committed_identity():
    result = _result()
    result["revision"] = {
        "revisionId": "cmap-import-1",
        "contentHash": "d" * 64,
        "snapshot": {"sources": ["x" * 20_000_000]},
        "diff": [{"oldValue": "x" * 20_000_000}],
        "reason": "x" * 20_000_000,
        "evidence": ["x" * 20_000_000],
    }
    result["activation"] = {
        "operationId": "operation-1",
        "phase": "reconciled",
        "revisionHash": "d" * 64,
        "previousSnapshot": {"sources": ["x" * 20_000_000]},
    }
    result["session"]["reason"] = "x" * 20_000_000
    result["opaqueExtension"] = "x" * 20_000_000
    before = deepcopy(result)
    output = _report_json(result)
    compact = json.loads(output)
    assert len((output + "\n").encode("utf-8")) <= 16 * 1024 * 1024
    assert compact["status"] == "active-draft"
    assert compact["revision"]["revisionId"] == "cmap-import-1"
    assert compact["revision"]["contentHash"] == "d" * 64
    assert compact["activation"]["phase"] == "reconciled"
    assert compact["activation"]["operationId"] == "operation-1"
    assert compact["session"]["refs"] == before["session"]["refs"]
    assert compact["readiness"] == before["readiness"]
    assert compact["truncated"] is True
    assert result == before


def test_extreme_findings_drop_whole_scopes_with_complete_counts():
    result = _result()
    result["status"] = "blocked"
    result["findings"] = [
        {
            "code": "OTIO_TEST_BLOCKER",
            "scope": "/" + str(index) + "界" * 1800,
            "blocking": True,
            "message": "x" * 2000,
            "remediation": "y" * 2000,
        }
        for index in range(4000)
    ]
    before = deepcopy(result)
    output = _report_json(result)
    compact = json.loads(output)
    assert len((output + "\n").encode("utf-8")) <= 16 * 1024 * 1024
    assert compact["findingCounts"] == {"total": 4000, "OTIO_TEST_BLOCKER": 4000}
    assert compact["findingsTruncated"] is True
    assert len(compact["findings"]) < 4000
    assert {row["scope"] for row in compact["findings"]} <= {
        row["scope"] for row in before["findings"]
    }
    assert compact["status"] == "blocked"
    assert compact["readiness"] == before["readiness"]
    assert result == before


def test_duplicate_findings_retain_blocking_state_and_total_count():
    result = _result()
    result["proposal"] = {"snapshot": {"opaque": "x" * 20_000_000}}
    result["findings"] = [
        {"code": "SAME", "scope": "/clip", "blocking": False, "message": "first"},
        {"code": "SAME", "scope": "/clip", "blocking": True, "message": "second"},
    ]
    compact = json.loads(_report_json(result))
    assert len(compact["findings"]) == 1
    assert compact["findings"][0]["blocking"] is True
    assert compact["findingCounts"] == {"total": 2, "SAME": 2}
