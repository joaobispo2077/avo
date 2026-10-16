from __future__ import annotations

import json

from avo.timeline.review import classify_findings, run_fix_loop


def test_labeled_finding_policy_executes_safe_fix_loop_without_unsafe_fixes(tmp_path):
    """Exercise repair orchestration; this is not a measured repair success rate."""
    corpus = [
        {"classification": "technical", "id": f"technical-{index}", "safe": True}
        for index in range(10)
    ] + [
        {"classification": classification, "id": classification, "safe": False}
        for classification in ("meaning", "rights", "privacy", "policy", "safety")
    ]
    for item in corpus:
        artifact = tmp_path / f"{item['id']}.json"
        artifact.write_text(json.dumps([item]), encoding="utf-8")
        calls = []

        def inspect(artifact=artifact):
            return json.loads(artifact.read_text(encoding="utf-8"))

        def fix(
            findings, artifact=artifact, calls=calls, revision=f"revision-{item['id']}"
        ):
            calls.extend(findings)
            artifact.write_text("[]", encoding="utf-8")
            return revision

        result = run_fix_loop(inspect, fix)
        state = classify_findings([item])
        if item["safe"]:
            assert state == "fixing"
            assert result["state"] == "ai-passed"
            assert result["attempts"][0]["fixRevision"] == f"revision-{item['id']}"
            assert calls == [item]
            assert inspect() == []
        else:
            assert state == "needs-human-judgment"
            assert result["state"] == state
            assert result["attempts"] == []
            assert calls == []
            assert inspect() == [item]
