"""Immutable records and current-input admission for generated media."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .media_admission import is_code_drawn_asset, require_media_admission
from .store import StoreError, write_immutable_json


class GeneratedAssetError(RuntimeError):
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "PROOF_GENERATED_ASSET_INVALID",
            "message": str(self),
            "remediation": "regenerate and fingerprint the output before proof admission",
            "blocking": True,
        }


class GeneratedAssetService:
    def __init__(self, workspace: Any):
        self.workspace = workspace
        self.directory = Path(workspace.timeline_dir) / "generated-assets"

    def path(self, asset_id: str) -> Path:
        if not isinstance(asset_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]{2,63}", asset_id
        ):
            raise GeneratedAssetError("generated assetId is invalid")
        return self.directory / f"{asset_id}.json"

    @staticmethod
    def _seal(record: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(record)
        value.setdefault("schemaVersion", "1.0.0")
        value["recordHash"] = document_hash_excluding(value, "recordHash")
        return value

    @staticmethod
    def _validate(record: dict[str, Any]) -> dict[str, Any]:
        if record.get("recordHash") != document_hash_excluding(record, "recordHash"):
            raise GeneratedAssetError("generated asset record hash mismatch")
        try:
            validate_document(record, "avo.generated-asset.schema.json")
        except ContractError as exc:
            label = "code-drawn " if is_code_drawn_asset(record) else ""
            raise GeneratedAssetError(
                f"invalid {label}generated asset record: {exc}"
            ) from exc
        return record

    @staticmethod
    def _output(record: dict[str, Any]) -> None:
        expected = record["output"]
        locator = expected.get("locator")
        if not locator or not Path(locator).is_file():
            raise GeneratedAssetError(f"generated output is missing: {locator}")
        actual = file_fingerprint(Path(locator))
        if any(actual[key] != expected[key] for key in ("sha256", "sizeBytes")):
            raise GeneratedAssetError(
                "generated output fingerprint changed or mismatched"
            )

    @staticmethod
    def _recorded_output(path: Path) -> dict[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise GeneratedAssetError(
                f"cannot inspect canonical output inventory: {path}"
            ) from error
        if not isinstance(document, dict):
            raise GeneratedAssetError(f"invalid canonical output inventory: {path}")
        return document.get("output") or {}

    def _known_outputs(self) -> list[dict[str, Any]]:
        from .migration import inventory_historical_output_fingerprints

        raw_dir = getattr(self.workspace, "raw_dir", None)
        if raw_dir is None:
            raise GeneratedAssetError("code-drawn canonical workspace is required")
        known = inventory_historical_output_fingerprints(raw_dir)
        for path in sorted(
            (Path(self.workspace.timeline_dir) / "materializations").rglob("*.json")
        ):
            output = self._recorded_output(path)
            if output.get("sha256"):
                known.append({**output, "role": "proof"})
        return known

    def _current_originals(self) -> list[dict[str, Any]]:
        index = self.workspace.require_active("cmap")
        cmap = self.workspace.store("cmap").revision(index["headRevisionId"])
        originals = []
        for source in cmap["snapshot"].get("sources") or []:
            fingerprint = deepcopy(source.get("fingerprint") or {})
            if not fingerprint.get("locator") and source.get("locator"):
                fingerprint["locator"] = source["locator"]
            originals.append(
                {"sourceId": source["sourceId"], "fingerprint": fingerprint}
            )
        return originals

    def _registered_records(self) -> dict[str, dict[str, Any]]:
        assets = {}
        for path in sorted(self.directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # A reachable malformed record remains unavailable.
            if isinstance(record, dict) and record.get("assetId") == path.stem:
                assets[path.stem] = record
        return assets

    def _context(self) -> dict[str, Any]:
        return {
            "registered_originals": self._current_originals(),
            "known_outputs": self._known_outputs(),
            "generated_assets": self._registered_records(),
        }

    def validate_code_drawn_inputs(self, inputs: list[dict[str, Any]]) -> None:
        """Pre-browser closure/quarantine validation, not generated-output approval."""
        contributors = []
        for reference in inputs:
            role = reference["ancestryRole"]
            contributors.append(
                {
                    **deepcopy(reference["fingerprint"]),
                    "nodeId": reference["artifactId"],
                    "artifactId": reference["artifactId"],
                    "ancestryRole": role,
                    **(
                        {"kind": "generated", "assetId": reference["artifactId"]}
                        if role == "generated"
                        else {}
                    ),
                }
            )
        try:
            require_media_admission(contributors, **self._context())
        except (ValueError, OSError) as error:
            raise GeneratedAssetError(
                f"code-drawn input admission failed: {error}"
            ) from error

    def _read_code_drawn_lock(
        self, extension: dict[str, Any]
    ) -> tuple[Path, dict[str, Any]]:
        lock_ref = extension["inputLockRef"]
        lock_path = Path(lock_ref["path"])
        if not lock_path.is_absolute() or not lock_path.resolve().is_relative_to(
            Path(self.workspace.raw_dir).resolve()
        ):
            raise GeneratedAssetError(
                "code-drawn original input lock must belong to the canonical workspace"
            )
        if file_fingerprint(lock_path)["sha256"] != lock_ref["sha256"]:
            raise GeneratedAssetError(
                "code-drawn original input lock file fingerprint changed"
            )
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if lock["bindingMode"] != "canonical":
            raise GeneratedAssetError(
                "code-drawn admission requires a verified canonical binding"
            )
        return lock_path, lock

    @staticmethod
    def _require_receipt_identity(record: dict, verified: dict, manifest: dict) -> None:
        extension = record["parameters"]["codeDrawn"]
        expected = {
            "instanceId": verified["instanceId"],
            "manifestRef": verified["manifestRef"],
            "inputLockHash": verified["inputLockHash"],
            "renderContractHash": verified["renderContractHash"],
            "inputsHash": verified["inputsHash"],
            "canonicalInputLock": verified["canonicalInputLock"],
            "drawingRoute": manifest["drawingRoute"],
            "sourceRevision": manifest["sourceRevision"],
        }
        if any(extension.get(key) != value for key, value in expected.items()):
            raise GeneratedAssetError(
                "code-drawn receipt canonical/input binding mismatch"
            )
        if record["generator"] != verified["generator"]:
            raise GeneratedAssetError("code-drawn generator identity changed")
        expected_environment = {
            key: verified["environment"][key] for key in ("platform", "dependencies")
        }
        actual_environment = {
            key: record["environment"][key] for key in expected_environment
        }
        if actual_environment != expected_environment:
            raise GeneratedAssetError("code-drawn receipt environment mismatch")
        if (
            "seed" in record["environment"]
            and record["environment"]["seed"] != manifest["seed"]
        ):
            raise GeneratedAssetError("code-drawn receipt seed mismatch")

    @staticmethod
    def _require_receipt_inputs(
        record: dict, verified: dict, manifest: dict, lock_path: Path
    ) -> None:
        expected_inputs = [
            *verified["inputs"],
            {
                "artifactId": "input-lock:" + verified["instanceId"],
                "fingerprint": file_fingerprint(lock_path),
                "ancestryRole": "dependency",
            },
        ]
        if record["inputs"] != expected_inputs:
            raise GeneratedAssetError("code-drawn receipt input closure mismatch")
        source_free = not any(item.get("sourceRef") for item in manifest["assets"])
        if record["sourceFree"] != source_free:
            raise GeneratedAssetError("code-drawn source ancestry declaration mismatch")

    @staticmethod
    def _require_output_evidence(extension: dict, contract: dict) -> None:
        required = {
            **{
                key: contract[key]
                for key in ("width", "height", "frameRate", "frameCount", "alphaMode")
            },
            "silent": True,
            "codec": "ffv1",
            "pixelFormat": "bgra",
            "rgbaRoundTrip": "exact",
            "captureColorSpace": "srgb",
            "compositeColorSpace": "sdr-bt709",
        }
        if any(
            extension["outputVerification"].get(key) != value
            for key, value in required.items()
        ):
            raise GeneratedAssetError(
                "code-drawn output verification does not match the render contract"
            )

    @staticmethod
    def _require_frame_hashes(hashes: Any) -> None:
        if not isinstance(hashes, list) or len(hashes) != 10:
            raise GeneratedAssetError(
                "code-drawn independent-seek frame hashes are incomplete"
            )
        for value in hashes:
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[a-f0-9]{64}", value) is None
            ):
                raise GeneratedAssetError(
                    "code-drawn independent-seek frame hash is invalid"
                )

    def _require_seek_evidence(
        self, extension: dict, contract: dict, environment: dict
    ) -> None:
        evidence = extension["captureEvidence"]
        moments = [round(i * (contract["frameCount"] - 1) / 9) for i in range(10)]
        if evidence.get("frames") != moments or set(evidence.get("passes") or []) != {
            "repeat",
            "reverse",
            "fresh-session",
        }:
            raise GeneratedAssetError(
                "code-drawn independent-seek evidence is incomplete"
            )
        if evidence.get("environment") != environment:
            raise GeneratedAssetError(
                "code-drawn independent-seek environment is stale"
            )
        self._require_frame_hashes(evidence.get("rgbaSha256"))

    def _verify_code_drawn_record(
        self, record: dict[str, Any], environment: dict[str, Any] | None
    ) -> dict[str, Any]:
        if environment is None:
            raise GeneratedAssetError(
                "code-drawn admission requires fresh environment observations"
            )
        from avo.motion import load_composition, verify_code_drawn_lock

        self._validate(record)
        self._output(record)
        extension = record["parameters"]["codeDrawn"]
        lock_path, lock = self._read_code_drawn_lock(extension)
        composition = Path(extension["manifestRef"]["path"])
        verified = verify_code_drawn_lock(
            composition,
            lock,
            workspace=self.workspace,
            instance_id=extension["instanceId"],
            environment=environment,
        )
        manifest = load_composition(composition)
        self._require_receipt_identity(record, verified, manifest)
        self._require_receipt_inputs(record, verified, manifest, lock_path)
        self._require_output_evidence(extension, manifest["renderContract"])
        self._require_seek_evidence(
            extension, manifest["renderContract"], verified["environment"]
        )
        return deepcopy(record)

    def _freshness(
        self, record: dict[str, Any], environment: dict[str, Any] | None
    ) -> None:
        if not is_code_drawn_asset(record):
            return
        if environment is None:
            raise GeneratedAssetError(
                "code-drawn admission requires fresh environment observations"
            )
        try:
            context = self._context()
            context["generated_assets"][record["assetId"]] = record
            require_media_admission(
                [
                    {
                        "nodeId": record["assetId"],
                        "kind": "generated",
                        "assetId": record["assetId"],
                        **record["output"],
                    }
                ],
                **context,
                code_drawn_verifier=lambda value: self._verify_code_drawn_record(
                    value, environment
                ),
            )
        except (KeyError, ValueError, RuntimeError, OSError) as error:
            raise GeneratedAssetError(
                f"code-drawn admission failed: {error}"
            ) from error

    def register(
        self,
        record: dict[str, Any],
        *,
        code_drawn_environment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = self._seal(record)
        if is_code_drawn_asset(value) and code_drawn_environment is None:
            raise GeneratedAssetError(
                "code-drawn registration requires fresh environment observations"
            )
        self._validate(value)
        self._output(value)
        self._freshness(value, code_drawn_environment)
        try:
            write_immutable_json(self.path(value["assetId"]), value)
        except StoreError as error:
            raise GeneratedAssetError(str(error)) from error
        return deepcopy(value)

    def load(self, asset_id: str) -> dict[str, Any]:
        path = self.path(asset_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise GeneratedAssetError(
                f"cannot load generated asset {asset_id}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise GeneratedAssetError("generated asset record must be an object")
        self._validate(value)
        if value["assetId"] != asset_id:
            raise GeneratedAssetError("generated asset file identity mismatch")
        return deepcopy(value)

    def admit(
        self, asset_id: str, *, code_drawn_environment: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        value = self.load(asset_id)
        if value["reproducibility"] == "unverified":
            raise GeneratedAssetError(
                f"generated asset {asset_id} is reference-only until reproducibility is verified"
            )
        self._output(value)
        self._freshness(value, code_drawn_environment)
        return deepcopy(value)
