"""Read captured native JUnit events independently of CI job status."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _validator():
    name = "avo_ci_test_execution_receipts"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name("run_quality_gate.py")
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("execution receipt validator unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class _NoDocumentTypes(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("DTD and external entity declarations are unsupported")


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _counts(raw: bytes) -> dict[str, int]:
    root = ET.fromstring(raw, parser=ET.XMLParser(target=_NoDocumentTypes()))
    if _tag(root) not in {"testsuite", "testsuites"}:
        raise ValueError("XML is not a native JUnit testsuite document")
    parents = {child: parent for parent in root.iter() for child in parent}
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    categories = {"failure": "failed", "error": "errors", "skipped": "skipped"}
    for case in root.iter():
        if _tag(case) != "testcase":
            continue
        if _tag(parents[case]) != "testsuite":
            raise ValueError("testcase event is outside a testsuite")
        outcomes = {_tag(child) for child in case} & categories.keys()
        if len(outcomes) > 1:
            raise ValueError("testcase has conflicting outcome events")
        category = categories[next(iter(outcomes))] if outcomes else "passed"
        counts[category] += 1
        counts["total"] += 1
    if (
        counts["total"]
        != sum(counts[key] for key in categories.values()) + counts["passed"]
    ):
        raise ValueError("testcase outcome counts are inconsistent")
    return counts


def _source(record: dict, directory: Path, artifact: str) -> tuple[dict, bytes]:
    path = _validator()._evidence_path(record["path"], directory)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != record.get("sha256") or len(raw) != record.get("bytes"):
        raise ValueError("execution artifact changed after receipt validation")
    return {
        "artifact": artifact,
        "path": path.relative_to(directory.resolve()).as_posix(),
        "sha256": digest,
    }, raw


def read_test_evidence(
    directory: Path,
    *,
    sha: str,
    run_id: str,
    gate: str,
    artifact: str,
    junit_name: str,
) -> dict:
    """Return verified observed testcase counts, never job-derived estimates."""
    result = {"state": "UNAVAILABLE", "counts": None, "sources": [], "reason": ""}
    if not re.fullmatch(r"[a-z][a-z0-9-]*", gate):
        result["reason"] = "invalid execution gate key"
        return result
    validation = _validator().validate_receipt(
        directory / "gates" / gate / "gate.json",
        sha=sha,
        run_id=run_id,
        gate=gate,
        artifact_root=directory,
    )
    if not validation["valid"]:
        result["reason"] = validation["reason"]
        return result
    receipt = validation["receipt"]
    try:
        log, _raw_log = _source(receipt["log"], directory, artifact)
        result["sources"] = [log]
        expected = (directory / junit_name.replace("\\", "/")).resolve()
        if not expected.is_relative_to(directory.resolve()):
            raise ValueError("JUnit path escapes artifact root")
        matching = [
            item
            for item in receipt["artifacts"]
            if _validator()._evidence_path(item["path"], directory) == expected
        ]
        if len(matching) != 1 or matching[0].get("reason") is not None:
            raise ValueError("fresh native JUnit artifact unavailable")
        junit, raw = _source(matching[0], directory, artifact)
        result["sources"] = [junit, log]
        counts = _counts(raw)
        status = receipt["status"]
        if status != "PASS":
            state, reason = (
                "PARTIAL",
                f"Captured testcase events from {status} execution.",
            )
        elif not counts["total"]:
            state, reason = "PARTIAL", "No testcase events were captured."
        elif counts["failed"] or counts["errors"]:
            state, reason = (
                "PARTIAL",
                "Passing execution receipt contradicts failing testcase events.",
            )
        else:
            state, reason = (
                "MEASURED",
                "Counts from actual native JUnit testcase events.",
            )
        result.update(state=state, counts=counts, reason=reason)
    except (OSError, ValueError, TypeError, KeyError, ET.ParseError) as exc:
        result["reason"] = str(exc)
    return result
