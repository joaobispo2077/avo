"""Project-owned component instances and external customization scaffolds."""

from __future__ import annotations

import json
import shutil
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


class ComponentInstanceError(RuntimeError):
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "PROOF_COMPONENT_INVALID",
            "message": str(self),
            "remediation": (
                "repair the project-local component contract and register it again"
            ),
            "blocking": True,
        }


class ComponentInstanceService:
    def __init__(self, workspace: Any):
        self.workspace = workspace
        self.directory = Path(workspace.timeline_dir) / "component-instances"

    def path(self, instance_id: str) -> Path:
        return self.directory / f"{instance_id}.json"

    @staticmethod
    def _seal(instance: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(instance)
        value.setdefault("schemaVersion", "1.0.0")
        value["instanceHash"] = document_hash_excluding(value, "instanceHash")
        return value

    @staticmethod
    def _validate(instance: dict[str, Any]) -> dict[str, Any]:
        if instance.get("instanceHash") != document_hash_excluding(
            instance, "instanceHash"
        ):
            raise ComponentInstanceError("component instance hash mismatch")
        try:
            validate_document(instance, "avo.component-instance.schema.json")
        except ContractError as exc:
            raise ComponentInstanceError(f"invalid component instance: {exc}") from exc
        return instance

    def register(
        self,
        instance: dict[str, Any],
        *,
        parameter_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = self._seal(instance)
        if parameter_schema is not None:
            try:
                import jsonschema

                jsonschema.validate(value["parameters"], parameter_schema)
            except Exception as exc:
                raise ComponentInstanceError(
                    f"component parameter contract failed: {exc}"
                ) from exc
        self._validate(value)
        for generated in value["generatedFiles"]:
            path = Path(generated["path"])
            if not path.is_file():
                raise ComponentInstanceError(f"component output is missing: {path}")
            if file_fingerprint(path)["sha256"] != generated["sha256"]:
                raise ComponentInstanceError(
                    f"component output fingerprint mismatch: {path}"
                )
        try:
            write_immutable_json(self.path(value["instanceId"]), value)
        except StoreError as exc:
            raise ComponentInstanceError(str(exc)) from exc
        return deepcopy(value)

    def load(self, instance_id: str) -> dict[str, Any]:
        path = self.path(instance_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ComponentInstanceError(
                f"cannot load component instance {instance_id}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise ComponentInstanceError("component instance must be an object")
        return deepcopy(self._validate(value))

    def implementation_reference(
        self,
        instance_id: str,
        *,
        adapter_id: str,
        kind: str = "project-component",
    ) -> dict[str, Any]:
        instance = self.load(instance_id)
        for item in instance["generatedFiles"]:
            path = Path(item["path"])
            if not path.is_file() or file_fingerprint(path)["sha256"] != item["sha256"]:
                raise ComponentInstanceError(
                    f"component output is no longer reproducible: {path}"
                )
        return {
            "implementationId": f"impl-{instance_id}"[:64],
            "kind": kind,
            "adapterId": adapter_id,
            "version": instance["kitVersion"],
            "sha256": instance["instanceHash"],
            "componentInstanceId": instance_id,
        }

    def resolve_provider_kit(
        self,
        *,
        catalog_path: Path,
        kit_id: str,
        version: str,
        manifest_hash: str,
        instance_id: str,
        parameters: dict[str, Any],
        asset_bindings: list[dict[str, Any]],
        event_bindings: list[dict[str, Any]],
        safe_area_bindings: dict[str, Any],
        sfx_bindings: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Copy one exact provider version into a fresh project-owned instance."""
        from .provider_animation import ProviderAnimationService

        catalog_path = Path(catalog_path)
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        provider = str(catalog.get("provider") or "")
        service = ProviderAnimationService(catalog_path, provider=provider)
        pattern = service.resolve_version(kit_id, version)
        manifest_ref = pattern.get("manifest") or {}
        if manifest_ref.get("sha256") != manifest_hash:
            raise ComponentInstanceError("provider kit manifest hash mismatch")
        ProviderAnimationService.validate_rights(pattern.get("rights") or [])
        source = (
            catalog_path.parent / "hyperframes" / kit_id / "versions" / version
        ).resolve()
        manifest_path = source / "manifest.json"
        if not manifest_path.is_file():
            raise ComponentInstanceError("provider kit manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("manifestSha256") != manifest_hash
            or document_hash_excluding(manifest, "manifestSha256") != manifest_hash
        ):
            raise ComponentInstanceError("provider kit manifest is not immutable")
        raw_dir = Path(self.workspace.raw_dir).resolve()
        destination = (
            raw_dir / "edit" / "derived" / "provider-components" / instance_id
        ).resolve()
        try:
            destination.relative_to(raw_dir)
        except ValueError as exc:
            raise ComponentInstanceError(
                "component instance escaped the project"
            ) from exc
        if destination.exists():
            raise ComponentInstanceError("fresh component instance already exists")
        generated: list[dict[str, Any]] = []
        try:
            destination.mkdir(parents=True)
            for item in manifest["files"]:
                source_file = (source / item["path"]).resolve()
                target_file = (destination / item["path"]).resolve()
                source_file.relative_to(source)
                target_file.relative_to(destination)
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_file)
                fingerprint = file_fingerprint(target_file)
                if fingerprint["sha256"] != item["sha256"]:
                    raise ComponentInstanceError(
                        f"provider kit file fingerprint mismatch: {item['path']}"
                    )
                generated.append(
                    {"path": str(target_file), "sha256": fingerprint["sha256"]}
                )
            target_manifest = destination / "manifest.json"
            shutil.copy2(manifest_path, target_manifest)
            generated.append(
                {
                    "path": str(target_manifest),
                    "sha256": file_fingerprint(target_manifest)["sha256"],
                }
            )
            fresh_assets = deepcopy(asset_bindings)
            for slot, binding in sorted((sfx_bindings or {}).items()):
                fresh_assets.append(
                    {
                        "slot": f"sfx:{slot}",
                        "sha256": binding["sha256"],
                        "rightsRef": binding["rightsRef"],
                    }
                )
            return self.register(
                {
                    "instanceId": instance_id,
                    "kitId": kit_id,
                    "kitVersion": version,
                    "kitManifestHash": manifest_hash,
                    "parameters": deepcopy(parameters),
                    "assetBindings": fresh_assets,
                    "eventBindings": deepcopy(event_bindings),
                    "safeAreaBindings": deepcopy(safe_area_bindings),
                    "generatedFiles": generated,
                    "reviewRefs": [],
                },
                parameter_schema=pattern.get("parameterSchema"),
            )
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def scaffold(self, component_id: str) -> dict[str, Any]:
        """Create a minimal customization area in the external footage project."""
        raw_dir = Path(self.workspace.raw_dir).resolve()
        project_dir = (
            raw_dir / "edit" / "derived" / "components" / component_id
        ).resolve()
        try:
            project_dir.relative_to(raw_dir)
        except ValueError as exc:
            raise ComponentInstanceError(
                "component scaffold escaped the footage project"
            ) from exc
        project_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schemaVersion": "1.0.0",
            "componentId": component_id,
            "ownership": "project-local",
            "entrypoint": "component.py",
            "note": (
                "Implement only the unsupported custom delta; timing remains in "
                "ProofPlan."
            ),
        }
        write_immutable_json(project_dir / "component.json", manifest)
        source = (
            '"""Project-local custom delta. Timing is supplied by ProofPlan."""\n\n'
            "def render(context):\n"
            '    raise NotImplementedError("implement the registered custom delta")\n'
        )
        source_path = project_dir / "component.py"
        if source_path.exists():
            if source_path.read_text(encoding="utf-8") != source:
                raise ComponentInstanceError(
                    f"component scaffold already contains custom code: {source_path}"
                )
        else:
            source_path.write_text(source, encoding="utf-8", newline="\n")
        return {
            "componentId": component_id,
            "path": str(project_dir),
            "manifest": manifest,
        }
