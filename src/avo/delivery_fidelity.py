"""Profile-aware delivery fidelity policy and canonical-lineage evaluation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from avo.timeline.contracts import content_hash

DELIVERY_FIDELITY_POLICY_ID = "avo.delivery-fidelity"
DELIVERY_FIDELITY_CHECKPOINTS = frozenset({"pre-master", "deliver"})
APPROVAL_REQUIRED_OPERATIONS = frozenset({"crop", "reframe", "rotate"})


class DeliveryFidelityPolicyError(ValueError):
    """Raised when a delivery-fidelity profile is incomplete or contradictory."""


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DeliveryFidelityPolicyError(f"{field} must be a positive integer")
    return value


def _validated_frame_rate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeliveryFidelityPolicyError("renderContract.frameRate is required")
    result = deepcopy(value)
    _positive_int(result.get("num"), "renderContract.frameRate.num")
    _positive_int(result.get("den"), "renderContract.frameRate.den")
    tolerance = result.get("tolerance", 0.001)
    if not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise DeliveryFidelityPolicyError(
            "renderContract.frameRate.tolerance must be non-negative"
        )
    result["tolerance"] = float(tolerance)
    return result


def _validated_contract(render_contract: dict[str, Any]) -> dict[str, Any]:
    contract = deepcopy(render_contract)
    _positive_int(contract.get("width"), "renderContract.width")
    _positive_int(contract.get("height"), "renderContract.height")
    contract["frameRate"] = _validated_frame_rate(contract.get("frameRate"))
    allowed = contract.get("allowedTransformations")
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) and item for item in allowed
    ):
        raise DeliveryFidelityPolicyError(
            "renderContract.allowedTransformations must be a string array"
        )
    encoding_rules = contract.get("encodingRules", {})
    if not isinstance(encoding_rules, dict):
        raise DeliveryFidelityPolicyError(
            "renderContract.encodingRules must be an object"
        )
    contract["encodingRules"] = deepcopy(encoding_rules)
    return contract


def resolve_delivery_fidelity_policy(
    *,
    profile_id: str,
    render_contract: dict[str, Any],
    prohibited_base_classes: list[str] | None = None,
    role_rules: dict[str, Any] | None = None,
    setting_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate and hash one completely resolved delivery profile."""
    if not profile_id.strip():
        raise DeliveryFidelityPolicyError("profileId must not be empty")
    if role_rules is not None and not isinstance(role_rules, dict):
        raise DeliveryFidelityPolicyError("roleRules must be an object")
    body = {
        "policyId": DELIVERY_FIDELITY_POLICY_ID,
        "profileId": profile_id,
        "settingSources": deepcopy(setting_sources or {}),
        "renderContract": _validated_contract(render_contract),
        "prohibitedBaseClasses": list(
            prohibited_base_classes
            if prohibited_base_classes is not None
            else ["proof", "proxy"]
        ),
        "roleRules": deepcopy(role_rules or {}),
    }
    return {**body, "policyHash": content_hash(body)}


def _finding(
    finding_id: str,
    message: str,
    *,
    classification: str = "technical",
    node_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": finding_id,
        "classification": classification,
        "message": message,
    }
    if node_id:
        result["nodeId"] = node_id
    return result


def _blocked(finding_id: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "source-fidelity",
        "status": "error",
        "disposition": "blocked",
        "findings": [_finding(finding_id, message, classification="prerequisite")],
        "details": details,
    }


def _candidate_frame_rate(candidate: dict[str, Any]) -> float | None:
    value = candidate.get("frameRate")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, dict):
        return None
    num, den = value.get("num"), value.get("den")
    if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
        return float(num) / float(den)
    return None


def _details(materialization: dict[str, Any]) -> dict[str, Any]:
    policy = materialization.get("deliveryFidelityPolicy") or {}
    lineage = materialization.get("pictureLineage") or {}
    output = materialization.get("output") or {}
    return {
        "policyId": policy.get("policyId"),
        "profileId": policy.get("profileId"),
        "policyHash": materialization.get("deliveryFidelityPolicyHash"),
        "materializationHash": materialization.get("materializationHash"),
        "outputHash": output.get("sha256"),
        "lineageHash": materialization.get("pictureLineageHash"),
        "rootIds": list(lineage.get("rootIds") or []),
        "offendingNodeIds": [],
        "renderContract": policy.get("renderContract"),
    }


def _content_hash_without(document: dict[str, Any], field: str) -> str:
    return content_hash({key: value for key, value in document.items() if key != field})


def _hash_prerequisite_error(
    candidate: dict[str, Any], materialization: dict[str, Any]
) -> tuple[str, str] | None:
    expected = _content_hash_without(materialization, "materializationHash")
    if materialization.get("materializationHash") != expected:
        return (
            "materialization-hash-invalid",
            "assembly materialization content hash is invalid; re-materialize the current assembly",
        )
    output_hash = (materialization.get("output") or {}).get("sha256")
    if candidate.get("sha256") != output_hash:
        return (
            "candidate-output-mismatch",
            "review candidate bytes do not match the assembly materialization output",
        )
    return None


def _stale_lock_error(
    materialization: dict[str, Any],
    current_revision_hashes: dict[str, str] | None,
    details: dict[str, Any],
) -> tuple[str, str] | None:
    if not current_revision_hashes:
        return None
    lock = materialization.get("canonicalInputLock") or {}
    stale = {
        key: {"expected": expected, "actual": lock.get(key)}
        for key, expected in current_revision_hashes.items()
        if lock.get(key) != expected
    }
    if not stale:
        return None
    details["staleLocks"] = stale
    return (
        "canonical-lock-stale",
        "assembly materialization does not match the current approved timeline revisions",
    )


def _policy_error(materialization: dict[str, Any]) -> tuple[str, str] | None:
    policy = materialization.get("deliveryFidelityPolicy") or {}
    if not policy:
        return (
            "fidelity-prerequisite-missing",
            "assembly materialization is missing resolved policy or picture lineage",
        )
    policy_hash = _content_hash_without(policy, "policyHash")
    if (
        policy.get("policyHash") != policy_hash
        or materialization.get("deliveryFidelityPolicyHash") != policy_hash
    ):
        return (
            "delivery-policy-stale",
            "resolved delivery-fidelity policy hash is missing or stale",
        )
    contract = policy.get("renderContract") or {}
    if materialization.get("renderContract") != contract or materialization.get(
        "renderContractHash"
    ) != content_hash(contract):
        return (
            "render-contract-stale",
            "resolved render contract is missing, contradictory, or stale",
        )
    return None


def _node_identity_error(nodes: list[dict[str, Any]]) -> str | None:
    node_ids = [str(node.get("nodeId") or "") for node in nodes]
    if any(not node_id for node_id in node_ids) or len(node_ids) != len(set(node_ids)):
        return "picture lineage node identities are missing or duplicated"
    return None


def _graph_reference_error(nodes, edges, roots) -> str | None:
    known = {str(node.get("nodeId") or "") for node in nodes}
    unknown_root = any(root not in known for root in roots)
    unknown_edge = any(
        edge.get("from") not in known or edge.get("to") not in known for edge in edges
    )
    if unknown_root or unknown_edge:
        return "picture lineage roots or edges reference unknown nodes"
    return None


def _fingerprint_error(nodes: list[dict[str, Any]]) -> str | None:
    missing = any(
        node.get("pictureCarrying", True) and len(str(node.get("sha256") or "")) != 64
        for node in nodes
    )
    if missing:
        return "picture-carrying lineage contributors require complete fingerprints"
    return None


def _graph_shape_error(lineage: dict[str, Any]) -> tuple[str, str] | None:
    nodes = lineage.get("nodes") or []
    edges = lineage.get("edges") or []
    roots = lineage.get("rootIds") or []
    if not nodes or not edges or not roots:
        return (
            "picture-lineage-incomplete",
            "picture lineage requires nodes, edges, and at least one output root",
        )
    message = (
        _node_identity_error(nodes)
        or _graph_reference_error(nodes, edges, roots)
        or _fingerprint_error(nodes)
    )
    return ("picture-lineage-incomplete", message) if message else None


def _lineage_error(materialization: dict[str, Any]) -> tuple[str, str] | None:
    lineage = materialization.get("pictureLineage") or {}
    if not lineage:
        return (
            "fidelity-prerequisite-missing",
            "assembly materialization is missing resolved policy or picture lineage",
        )
    shape_error = _graph_shape_error(lineage)
    if shape_error:
        return shape_error
    lineage_hash = _content_hash_without(lineage, "pictureLineageHash")
    if (
        lineage.get("pictureLineageHash") != lineage_hash
        or materialization.get("pictureLineageHash") != lineage_hash
    ):
        return (
            "picture-lineage-invalid",
            "picture lineage is incomplete or its content hash is invalid",
        )
    return None


def _prerequisite_error(
    *,
    candidate: dict[str, Any],
    materialization: dict[str, Any],
    current_revision_hashes: dict[str, str] | None,
    details: dict[str, Any],
) -> tuple[str, str] | None:
    checks = (
        _hash_prerequisite_error(candidate, materialization),
        _stale_lock_error(materialization, current_revision_hashes, details),
        _policy_error(materialization),
        _lineage_error(materialization),
    )
    return next((error for error in checks if error), None)


def _edge_findings(edge, allowed, profile_id) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    operation = str(edge.get("operation") or "")
    node_id = str(edge.get("to") or "") or None
    if operation not in allowed:
        findings.append(
            _finding(
                "transformation-not-allowed",
                f"lineage operation {operation!r} is not allowed by profile {profile_id!r}",
                node_id=node_id,
            )
        )
    if operation in APPROVAL_REQUIRED_OPERATIONS and not edge.get("approvalReference"):
        findings.append(
            _finding(
                "transformation-approval-missing",
                f"lineage operation {operation!r} requires an approval reference",
                node_id=node_id,
            )
        )
    return findings


def _transformation_findings(
    policy: dict[str, Any], lineage: dict[str, Any]
) -> list[dict[str, Any]]:
    allowed = set(
        (policy.get("renderContract") or {}).get("allowedTransformations") or []
    )
    return [
        finding
        for edge in lineage.get("edges") or []
        for finding in _edge_findings(edge, allowed, policy.get("profileId"))
    ]


def _dimension_findings(
    candidate: dict[str, Any], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for field in ("width", "height"):
        if int(candidate.get(field) or 0) != int(contract.get(field) or 0):
            findings.append(
                _finding(
                    f"render-{field}-mismatch",
                    f"candidate {field} {candidate.get(field)!r} does not match declared {contract.get(field)!r}",
                )
            )
    return findings


def _frame_rate_finding(candidate, contract) -> dict[str, Any] | None:
    expected_rate = contract.get("frameRate") or {}
    expected_fps = float(expected_rate.get("num") or 0) / float(
        expected_rate.get("den") or 1
    )
    candidate_fps = _candidate_frame_rate(candidate)
    tolerance = float(expected_rate.get("tolerance") or 0)
    if candidate_fps is None or abs(candidate_fps - expected_fps) > tolerance:
        return _finding(
            "render-frame-rate-mismatch",
            "candidate frame rate does not match the declared render contract",
        )
    return None


def _geometry_findings(candidate, contract) -> list[dict[str, Any]]:
    findings = _dimension_findings(candidate, contract)
    frame_rate_finding = _frame_rate_finding(candidate, contract)
    return findings + ([frame_rate_finding] if frame_rate_finding else [])


def _duration_finding(
    candidate: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any] | None:
    expected = contract.get("durationSeconds")
    if expected is None:
        return None
    tolerance = float(contract.get("durationToleranceSec") or 0)
    actual = float(candidate.get("durationSeconds") or 0)
    if abs(actual - float(expected)) <= tolerance:
        return None
    return _finding(
        "render-duration-mismatch",
        "candidate duration is outside the declared tolerance",
    )


def _encoding_finding(
    candidate: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any] | None:
    codec = str(candidate.get("codec") or "").lower()
    codec_rules = (contract.get("encodingRules") or {}).get(codec) or {}
    minimum = int(codec_rules.get("minimumBitRate") or 0)
    if not minimum or int(candidate.get("bitRate") or 0) >= minimum:
        return None
    return _finding(
        "codec-bitrate-below-profile",
        f"candidate {codec} bitrate is below the declared profile minimum",
    )


def _role_violation(node: dict[str, Any], policy: dict[str, Any]) -> bool:
    role = str(node.get("role") or "")
    media_class = str(node.get("mediaClass") or "")
    rule = (policy.get("roleRules") or {}).get(role) or {}
    prohibited = set(rule.get("prohibitedMediaClasses") or [])
    allowed = rule.get("allowedMediaClasses")
    base_prohibited = set(policy.get("prohibitedBaseClasses") or [])
    violations = (
        role == "base" and media_class in base_prohibited,
        media_class in prohibited,
        allowed is not None and media_class not in allowed,
    )
    return any(violations)


def _role_resolution_violation(node: dict[str, Any], policy: dict[str, Any]) -> bool:
    rule = (policy.get("roleRules") or {}).get(str(node.get("role") or "")) or {}
    media = node.get("media") or {}
    for dimension in ("width", "height"):
        minimum = int(rule.get(f"minimum{dimension.title()}") or 0)
        if minimum and int(media.get(dimension) or 0) < minimum:
            return True
    return False


def _ancestry_findings(
    policy: dict[str, Any], lineage: dict[str, Any], details: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for node in lineage.get("nodes") or []:
        if not node.get("pictureCarrying", True):
            continue
        node_id = str(node.get("nodeId") or "")
        if _role_violation(node, policy):
            details["offendingNodeIds"].append(node_id)
            findings.append(
                _finding(
                    "prohibited-picture-ancestor",
                    f"{node.get('mediaClass')!r} is prohibited for picture role {node.get('role')!r}",
                    node_id=node_id,
                )
            )
        if _role_resolution_violation(node, policy):
            details["offendingNodeIds"].append(node_id)
            findings.append(
                _finding(
                    "picture-role-resolution-below-profile",
                    f"picture contributor does not satisfy role {node.get('role')!r} resolution policy",
                    node_id=node_id,
                )
            )
    details["offendingNodeIds"] = list(dict.fromkeys(details["offendingNodeIds"]))
    return findings


def evaluate_delivery_fidelity(
    *,
    checkpoint: str,
    candidate: dict[str, Any],
    materialization: dict[str, Any] | None,
    current_revision_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate a candidate in contract order and distinguish blocked from fail."""
    if checkpoint not in DELIVERY_FIDELITY_CHECKPOINTS:
        return {
            "kind": "source-fidelity",
            "status": "not-applicable",
            "disposition": "not-applicable",
            "findings": [],
            "details": {},
        }
    if not materialization:
        return _blocked(
            "materialization-missing",
            "pre-master/deliver requires a canonical assembly materialization; re-materialize the current assembly",
            {},
        )

    details = _details(materialization)
    prerequisite_error = _prerequisite_error(
        candidate=candidate,
        materialization=materialization,
        current_revision_hashes=current_revision_hashes,
        details=details,
    )
    if prerequisite_error:
        return _blocked(*prerequisite_error, details)

    policy = materialization["deliveryFidelityPolicy"]
    lineage = materialization["pictureLineage"]
    contract = policy["renderContract"]
    findings = _transformation_findings(policy, lineage)
    findings.extend(_geometry_findings(candidate, contract))
    for finding in (
        _duration_finding(candidate, contract),
        _encoding_finding(candidate, contract),
    ):
        if finding:
            findings.append(finding)
    findings.extend(_ancestry_findings(policy, lineage, details))
    disposition = "pass" if not findings else "fail"
    return {
        "kind": "source-fidelity",
        "status": disposition,
        "disposition": disposition,
        "findings": findings,
        "details": details,
    }
