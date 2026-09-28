"""Immutable records for generated media admitted before proof compilation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .store import StoreError, write_immutable_json


class GeneratedAssetError(RuntimeError):
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "PROOF_GENERATED_ASSET_INVALID",
            "message": str(self),
            "remediation": (
                "regenerate and fingerprint the output before proof admission"
            ),
            "blocking": True,
        }


class GeneratedAssetService:
    def __init__(self, workspace: Any):
        self.workspace = workspace
        self.directory = Path(workspace.timeline_dir) / "generated-assets"

    def path(self, asset_id: str) -> Path:
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
            raise GeneratedAssetError(f"invalid generated asset record: {exc}") from exc
        return record

    def register(self, record: dict[str, Any]) -> dict[str, Any]:
        value = self._seal(record)
        self._validate(value)
        locator = value["output"].get("locator")
        if not locator:
            raise GeneratedAssetError(
                "generated output locator is required for admission"
            )
        output_path = Path(locator)
        if not output_path.is_file():
            raise GeneratedAssetError(f"generated output is missing: {output_path}")
        actual = file_fingerprint(output_path)
        if actual["sha256"] != value["output"]["sha256"]:
            raise GeneratedAssetError("generated output fingerprint mismatch")
        if actual["sizeBytes"] != value["output"]["sizeBytes"]:
            raise GeneratedAssetError("generated output size mismatch")
        try:
            write_immutable_json(self.path(value["assetId"]), value)
        except StoreError as exc:
            raise GeneratedAssetError(str(exc)) from exc
        return deepcopy(value)

    def load(self, asset_id: str) -> dict[str, Any]:
        path = self.path(asset_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GeneratedAssetError(
                f"cannot load generated asset {asset_id}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise GeneratedAssetError("generated asset record must be an object")
        return deepcopy(self._validate(value))

    def admit(self, asset_id: str) -> dict[str, Any]:
        value = self.load(asset_id)
        if value["reproducibility"] == "unverified":
            raise GeneratedAssetError(
                f"generated asset {asset_id} is reference-only until "
                "reproducibility is verified"
            )
        locator = value["output"].get("locator")
        if not locator or not Path(locator).is_file():
            raise GeneratedAssetError(f"generated output is missing: {locator}")
        actual = file_fingerprint(Path(locator))
        if actual["sha256"] != value["output"]["sha256"]:
            raise GeneratedAssetError("generated output changed after registration")
        return deepcopy(value)
