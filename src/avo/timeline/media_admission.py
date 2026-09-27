"""Allowlist admission for proof media and recursive generated assets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .contracts import file_fingerprint

FORBIDDEN_OUTPUT_CLASSES = frozenset(
    {"proof", "preview", "proxy", "master", "delivery"}
)


class MediaAdmissionError(ValueError):
    def __init__(self, code: str, finding: dict[str, Any]):
        self.code = code
        self.finding = finding
        super().__init__(f"{code}: {finding.get('reason', 'media admission failed')}")


def validate_still_admission(*, purpose: str, input_kind: str) -> None:
    """Keep candidate frames out of proofs and thumbnails approval-bound."""
    valid_purposes = {"thumbnail", "review", "reference", "canonical-generated-asset"}
    valid_inputs = {"raw-source", "program", "current-candidate", "approved-candidate"}
    if purpose not in valid_purposes or input_kind not in valid_inputs:
        raise ValueError("unsupported still purpose or input kind")
    if purpose == "thumbnail" and input_kind != "approved-candidate":
        raise ValueError("thumbnail extraction requires an approved-candidate")
    if "candidate" in input_kind and purpose == "canonical-generated-asset":
        raise ValueError("candidate-derived still cannot enter a proof")
    if input_kind == "current-candidate" and purpose not in {"review", "reference"}:
        raise ValueError("current-candidate still is review/reference only")


def _records_by_id(
    values: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    if isinstance(values, Mapping):
        return {str(record.get(key) or name): record for name, record in values.items()}
    return {str(record.get(key) or ""): record for record in values}


def _fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    return value.get("fingerprint") or value.get("output") or value


def _sha256(value: dict[str, Any]) -> str:
    return str(_fingerprint(value).get("sha256") or "")


def _finding(value: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    fingerprint = _fingerprint(value)
    return {
        "nodeId": str(value.get("nodeId") or ""),
        "artifactId": str(value.get("artifactId") or value.get("assetId") or ""),
        "locator": str(value.get("locator") or fingerprint.get("locator") or ""),
        "sha256": str(fingerprint.get("sha256") or ""),
        "reason": reason,
        **extra,
    }


def _media_class(value: dict[str, Any]) -> str:
    provenance = value.get("provenance") or {}
    return str(
        value.get("artifactRole")
        or value.get("mediaClass")
        or provenance.get("mediaClass")
        or value.get("role")
        or ""
    ).lower()


def _verify_locator(value: dict[str, Any]) -> None:
    fingerprint = _fingerprint(value)
    locator = str(value.get("locator") or fingerprint.get("locator") or "")
    expected = str(fingerprint.get("sha256") or "")
    if not locator or not Path(locator).is_file() or not expected:
        return
    actual = file_fingerprint(Path(locator))["sha256"]
    if actual != expected:
        raise MediaAdmissionError(
            "PROOF_MEDIA_FINGERPRINT_MISMATCH",
            _finding(value, "fingerprint-mismatch", actualSha256=actual),
        )


def require_no_forbidden_outputs(
    contributors: Iterable[dict[str, Any]],
    *,
    known_outputs: Iterable[dict[str, Any]] = (),
) -> None:
    """Apply the output quarantine without requiring a complete new registry."""
    outputs = {_sha256(record): record for record in known_outputs if _sha256(record)}
    for contributor in contributors:
        known = outputs.get(_sha256(contributor))
        media_class = _media_class(known or contributor)
        if media_class in FORBIDDEN_OUTPUT_CLASSES:
            raise MediaAdmissionError(
                "PROOF_FORBIDDEN_ANCESTOR",
                _finding(
                    contributor,
                    "forbidden-output-ancestor",
                    outputRole=media_class,
                ),
            )


def require_media_admission(
    contributors: Iterable[dict[str, Any]],
    *,
    registered_originals: Iterable[dict[str, Any]] = (),
    generated_assets: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]] = (),
    known_outputs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Admit only exact originals or recursively complete generated assets."""
    originals = list(registered_originals)
    originals_by_sha = {
        _sha256(record): record for record in originals if _sha256(record)
    }
    originals_by_id = {
        str(record.get("sourceId") or record.get("artifactId") or ""): record
        for record in originals
    }
    assets = _records_by_id(generated_assets, "assetId")
    outputs = {_sha256(record): record for record in known_outputs if _sha256(record)}
    admitted: list[dict[str, str]] = []
    visited: set[str] = set()

    def reject_known(value: dict[str, Any]) -> None:
        media_class = _media_class(value)
        known = outputs.get(_sha256(value))
        if media_class in FORBIDDEN_OUTPUT_CLASSES or known is not None:
            role = _media_class(known or value) or media_class
            raise MediaAdmissionError(
                "PROOF_FORBIDDEN_ANCESTOR",
                _finding(value, "forbidden-output-ancestor", outputRole=role),
            )

    def admit_reference(reference: dict[str, Any], stack: tuple[str, ...]) -> None:
        reject_known(reference)
        artifact_id = str(reference.get("artifactId") or "")
        sha256 = _sha256(reference)
        if artifact_id in assets:
            record = assets[artifact_id]
            if sha256 and sha256 != _sha256(record):
                raise MediaAdmissionError(
                    "PROOF_MEDIA_FINGERPRINT_MISMATCH",
                    _finding(reference, "generated-asset-output-mismatch"),
                )
            admit_asset(record, stack)
            return
        original = originals_by_id.get(artifact_id) or originals_by_sha.get(sha256)
        if original is not None and (not sha256 or sha256 == _sha256(original)):
            return
        raise MediaAdmissionError(
            "PROOF_MEDIA_QUARANTINED",
            _finding(reference, "unregistered-or-ambiguous"),
        )

    def admit_asset(record: dict[str, Any], stack: tuple[str, ...]) -> None:
        asset_id = str(record.get("assetId") or "")
        if not asset_id:
            raise MediaAdmissionError(
                "PROOF_MEDIA_QUARANTINED",
                _finding(record, "generated-asset-id-missing"),
            )
        if asset_id in stack:
            raise MediaAdmissionError(
                "PROOF_ANCESTRY_CYCLE",
                _finding(record, "generated-asset-cycle", cycle=[*stack, asset_id]),
            )
        if asset_id in visited:
            return
        reject_known(record)
        reproducibility = str(record.get("reproducibility") or "unverified")
        if reproducibility == "unverified" or (
            reproducibility == "declared" and not record.get("approvalReference")
        ):
            raise MediaAdmissionError(
                "PROOF_MEDIA_QUARANTINED",
                _finding(record, "generated-asset-not-admissible"),
            )
        inputs = list(record.get("inputs") or [])
        if not inputs and not record.get("sourceFree", False):
            raise MediaAdmissionError(
                "PROOF_MEDIA_QUARANTINED",
                _finding(record, "generated-asset-ancestry-missing"),
            )
        for reference in inputs:
            admit_reference(reference, (*stack, asset_id))
        visited.add(asset_id)

    for contributor in contributors:
        _verify_locator(contributor)
        reject_known(contributor)
        sha256 = _sha256(contributor)
        asset_id = str(
            contributor.get("assetId") or contributor.get("generatedAssetId") or ""
        )
        if asset_id or contributor.get("kind") == "generated":
            record = assets.get(asset_id)
            if record is None or sha256 != _sha256(record):
                raise MediaAdmissionError(
                    "PROOF_MEDIA_QUARANTINED",
                    _finding(contributor, "unregistered-or-ambiguous"),
                )
            admit_asset(record, ())
            admission = "canonical-generated-asset"
        elif sha256 in originals_by_sha:
            admission = "registered-original"
        else:
            raise MediaAdmissionError(
                "PROOF_MEDIA_QUARANTINED",
                _finding(contributor, "unregistered-or-ambiguous"),
            )
        admitted.append(
            {"nodeId": str(contributor.get("nodeId") or ""), "admission": admission}
        )
    return {"status": "pass", "admitted": admitted, "quarantined": []}
