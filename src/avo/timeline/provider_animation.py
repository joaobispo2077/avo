"""Sanitized proposal and immutable publication of provider animation kits."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .animation import AnimationError, _keys
from .contracts import content_hash, file_fingerprint, validate_document
from .store import atomic_write_json, now_iso

FORBIDDEN_FIELDS = {
    "text",
    "timestamps",
    "timestamp",
    "timing",
    "claims",
    "screenshots",
    "footage",
    "media",
    "projectPath",
    "assetPath",
    "locator",
    "absolutePath",
}
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_MEDIA = re.compile(
    r"\.(mp4|mov|mkv|avi|wav|mp3|png|jpe?g|webp|avif)(?:['\"?#]|$)", re.IGNORECASE
)
_SOURCE_REJECTIONS = (
    (
        re.compile(
            r"(?:https?|wss?)://|\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(",
            re.IGNORECASE,
        ),
        "network access",
    ),
    (re.compile(r"\burl\s*\(", re.IGNORECASE), "CSS URL"),
    (re.compile(r"sourceMappingURL", re.IGNORECASE), "source map"),
    (
        re.compile(
            r"(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\s*[:=]",
            re.IGNORECASE,
        ),
        "secret",
    ),
    (
        re.compile(
            r"(?:[A-Za-z]:[\\/]|file://|/(?:Users|home|mnt|private|tmp)/)",
            re.IGNORECASE,
        ),
        "absolute path",
    ),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b"), "timestamp"),
    (_MEDIA, "media reference"),
)
_RIGHTS_REQUIRED = {
    "dependencyId",
    "sha256",
    "owner",
    "source",
    "license",
    "evidenceRef",
    "derivativesAllowed",
    "providerWide",
    "commercialUse",
    "attribution",
    "territory",
    "termEndsAt",
    "revoked",
    "aiDisclosure",
}


class ProviderAnimationService:
    def __init__(
        self, catalog_path: Path, *, provider: str, clock: Callable[[], str] = now_iso
    ):
        self.path = Path(catalog_path)
        self.provider = provider
        self.clock = clock

    def initialize(self) -> dict[str, Any]:
        if not self.path.exists():
            atomic_write_json(
                self.path,
                {
                    "schemaVersion": "1.0.0",
                    "provider": self.provider,
                    "patterns": [],
                    "events": [],
                },
            )
        return self.load()

    def load(self) -> dict[str, Any]:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        validate_document(
            value,
            "avo.animation-library.schema.json",
            root=Path(__file__).resolve().parents[3] / "providers",
        )
        return value

    @staticmethod
    def sanitize(pattern: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(pattern)
        forbidden = _keys(value) & FORBIDDEN_FIELDS
        if forbidden:
            raise AnimationError(
                "provider pattern contains project-specific content: "
                + ", ".join(sorted(forbidden))
            )
        for leaf in _string_leaves(value):
            if _looks_absolute(leaf) or _MEDIA.search(leaf):
                raise AnimationError(
                    "provider pattern leaks a project path/media reference"
                )
        required = {
            "patternId",
            "name",
            "version",
            "behavior",
            "contexts",
            "exclusions",
            "requiredAssets",
            "accessibility",
            "provenance",
        }
        missing = required - set(value)
        if missing:
            raise AnimationError(
                "pattern missing generalized fields: " + ", ".join(sorted(missing))
            )
        if not _SEMVER.fullmatch(str(value["version"])):
            raise AnimationError(
                "provider animation version must be semantic MAJOR.MINOR.PATCH"
            )
        return value

    @staticmethod
    def validate_rights(
        entries: list[dict[str, Any]], *, now: datetime | None = None
    ) -> dict[str, Any]:
        if not entries:
            raise AnimationError("rights manifest is required")
        now = now or datetime.now(timezone.utc)
        for entry in entries:
            missing = _RIGHTS_REQUIRED - set(entry)
            if missing:
                raise AnimationError(
                    "rights entry missing: " + ", ".join(sorted(missing))
                )
            if not re.fullmatch(r"[a-f0-9]{64}", str(entry["sha256"])):
                raise AnimationError("rights dependency fingerprint is invalid")
            if entry["revoked"] or not all(
                entry[key]
                for key in ("derivativesAllowed", "providerWide", "commercialUse")
            ):
                raise AnimationError("rights are revoked or not provider-portable")
            end = entry.get("termEndsAt")
            if end:
                try:
                    expiry = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                except ValueError as exc:
                    raise AnimationError("rights expiry is invalid") from exc
                if expiry <= now:
                    raise AnimationError("rights have expired")
            for key in (
                "owner",
                "source",
                "license",
                "evidenceRef",
                "territory",
                "attribution",
                "aiDisclosure",
            ):
                if not str(entry.get(key) or "").strip():
                    raise AnimationError(f"rights {key} is ambiguous")
        return {
            "eligible": True,
            "checkedAt": now.isoformat().replace("+00:00", "Z"),
            "attributions": sorted({str(i["attribution"]) for i in entries}),
            "aiDisclosures": sorted({str(i["aiDisclosure"]) for i in entries}),
        }

    def propose(
        self, pattern: dict[str, Any], *, actor: str, intent_reference: str
    ) -> dict[str, Any]:
        if not actor or not intent_reference:
            raise AnimationError("explicit creator promotion intent is required")
        return self._write_proposal(
            {
                "schemaVersion": "1.0.0",
                "provider": self.provider,
                "pattern": self.sanitize(pattern),
                "actor": actor,
                "intentReference": intent_reference,
                "createdAt": self.clock(),
            }
        )

    def propose_from_project(
        self,
        pattern: dict[str, Any],
        *,
        project_root: Path,
        selected_files: Iterable[str],
        parameter_schema: dict[str, Any],
        dependency_lock: dict[str, dict[str, str]],
        rights: list[dict[str, Any]],
        fixtures: list[dict[str, Any]],
        actor: str,
        intent_reference: str,
        visible_text_authorized: bool = False,
        validator: Callable[[str, Path, dict[str, Any] | None], Any] | None = None,
        change_type: str = "major",
        learning_ref: str | None = None,
    ) -> dict[str, Any]:
        if not actor or not intent_reference:
            raise AnimationError("explicit creator promotion intent is required")
        sanitized = self.sanitize(pattern)
        root = Path(project_root).resolve()
        files: list[dict[str, Any]] = []
        for relative in sorted(set(selected_files)):
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise AnimationError(
                    "selected component escaped the project root"
                ) from exc
            if not candidate.is_file() or candidate.is_symlink():
                raise AnimationError(
                    f"selected component file is unavailable: {relative}"
                )
            text = candidate.read_text(encoding="utf-8")
            self._validate_source(text, visible_text_authorized=visible_text_authorized)
            files.append(
                {
                    "path": Path(relative).as_posix(),
                    "sha256": file_fingerprint(candidate)["sha256"],
                    "content": text,
                }
            )
        if not files:
            raise AnimationError("proposal requires selected component files")
        if parameter_schema.get("type") != "object":
            raise AnimationError("typed parameter schema must describe an object")
        for name, locked in dependency_lock.items():
            if not str(locked.get("version") or "") or not re.fullmatch(
                r"[a-f0-9]{64}", str(locked.get("sha256") or "")
            ):
                raise AnimationError(f"dependency lock is incomplete: {name}")
        rights_report = self.validate_rights(rights)
        uncovered = set(dependency_lock) - {
            str(item["dependencyId"]) for item in rights
        }
        if uncovered:
            raise AnimationError(
                "rights manifest does not cover dependencies: "
                + ", ".join(sorted(uncovered))
            )
        lifecycle = (sanitized.get("behavior") or {}).get("lifecycle") or {}
        if not {"preEntry", "entrance", "hold", "exit"} <= set(lifecycle):
            raise AnimationError("provider component requires a complete lifecycle")
        if len(fixtures) < 2 or not any(
            item.get("reducedMotion") is True for item in fixtures
        ):
            raise AnimationError(
                "at least two neutral fixtures including reduced motion are required"
            )
        if len({content_hash(item) for item in fixtures}) < 2:
            raise AnimationError(
                "neutral fixture configurations must be materially different"
            )
        try:
            import jsonschema

            for fixture in fixtures:
                jsonschema.validate(fixture.get("parameters") or {}, parameter_schema)
        except Exception as exc:
            raise AnimationError(
                f"neutral fixture parameter contract failed: {exc}"
            ) from exc
        validation = self._validate_fixtures(root, fixtures, validator)
        manifest = {
            "schemaVersion": "1.0.0",
            "kitId": sanitized["patternId"],
            "version": sanitized["version"],
            "parameterSchema": deepcopy(parameter_schema),
            "dependencies": deepcopy(dependency_lock),
            "rights": deepcopy(rights),
            "fixtures": deepcopy(fixtures),
            "lifecycle": deepcopy(lifecycle),
            "files": [{key: item[key] for key in ("path", "sha256")} for item in files],
        }
        manifest["manifestSha256"] = content_hash(manifest)
        sanitized.update(
            {
                "kitId": sanitized["patternId"],
                "parameterSchema": deepcopy(parameter_schema),
                "dependencyLock": deepcopy(dependency_lock),
                "rights": deepcopy(rights),
                "fixtures": deepcopy(fixtures),
                "lifecycle": manifest["lifecycle"],
                "manifest": {
                    "path": "manifest.json",
                    "sha256": manifest["manifestSha256"],
                },
                "status": "active",
            }
        )
        return self._write_proposal(
            {
                "schemaVersion": "1.0.0",
                "provider": self.provider,
                "pattern": sanitized,
                "kit": {"manifest": manifest, "files": files},
                "actor": actor,
                "intentReference": intent_reference,
                "createdAt": self.clock(),
                "changeType": change_type,
                "learningRef": learning_ref,
                "sanitizationReport": {
                    "eligible": True,
                    "visibleTextAuthorized": visible_text_authorized,
                    "fileCount": len(files),
                },
                "rightsReport": rights_report,
                "validationReport": validation,
                "generalizability": {
                    "eligible": True,
                    "typedParameters": True,
                    "privateDependencies": 0,
                    "neutralFixtureCount": len(fixtures),
                    "offlineDeterministic": True,
                    "portableRights": True,
                    "maintenanceJudgment": "reuse-approved",
                },
            }
        )

    @staticmethod
    def _validate_source(source: str, *, visible_text_authorized: bool) -> None:
        for expression, label in _SOURCE_REJECTIONS:
            if expression.search(source):
                raise AnimationError(f"provider component contains {label}")
        if "—" in source and not visible_text_authorized:
            raise AnimationError(
                "visible-text em dash requires explicit user authorization"
            )

    @staticmethod
    def _validate_fixtures(
        root: Path,
        fixtures: list[dict[str, Any]],
        validator: Callable[[str, Path, dict[str, Any] | None], Any] | None,
    ) -> dict[str, Any]:
        if validator is None:
            raise AnimationError(
                "HyperFrames validator is required for provider proposals"
            )
        for operation in ("lint", "check"):
            if validator(operation, root, None) is False:
                raise AnimationError(f"HyperFrames {operation} failed")
        for fixture in fixtures:
            if validator("snapshot", root, fixture) is False:
                raise AnimationError("HyperFrames snapshot failed")
            first = validator("render", root, fixture)
            second = validator("render", root, fixture)
            if first is False or second is False:
                raise AnimationError("HyperFrames render failed")
            if first != second:
                raise AnimationError("HyperFrames fixture render is not deterministic")
        return {
            "lint": "passed",
            "check": "passed",
            "fixtureCount": len(fixtures),
            "reducedMotion": True,
            "deterministic": True,
        }

    def _write_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        proposal["proposalSha256"] = content_hash(proposal)
        pattern = proposal["pattern"]
        path = (
            self.path.parent
            / "proposals"
            / f"{pattern['patternId']}-{pattern['version']}-{proposal['proposalSha256'][:12]}.json"
        )
        atomic_write_json(path, proposal)
        return {**proposal, "path": str(path)}

    def decide(
        self,
        proposal_path: Path,
        *,
        decision: str,
        actor: str,
        reason: str,
        expected_catalog_sha256: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise AnimationError("promotion decision must be approved or rejected")
        proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
        expected = content_hash(
            {
                key: value
                for key, value in proposal.items()
                if key not in {"proposalSha256", "path"}
            }
        )
        if proposal.get("proposalSha256") != expected:
            raise AnimationError("animation proposal hash mismatch")
        pattern = self.sanitize(proposal["pattern"])
        catalog = self.initialize()
        base_catalog_hash = content_hash(catalog)
        self._check_cas(catalog, expected_catalog_sha256)
        existing = next(
            (
                item
                for item in catalog["patterns"]
                if item["patternId"] == pattern["patternId"]
                and item["version"] == pattern["version"]
            ),
            None,
        )
        proposed_manifest = ((proposal.get("kit") or {}).get("manifest") or {}).get(
            "manifestSha256"
        )
        if decision == "approved" and existing is not None:
            if (
                proposed_manifest
                and (existing.get("manifest") or {}).get("sha256") == proposed_manifest
            ):
                return {
                    "type": "promotion-approved",
                    "patternId": pattern["patternId"],
                    "manifestSha256": proposed_manifest,
                    "publishedPath": str(self._version_path(pattern)),
                    "idempotent": True,
                }
            raise AnimationError(
                "immutable semantic version already exists with different bytes"
            )
        event = {
            "eventId": f"animation-event-{len(catalog['events']) + 1:04d}",
            "type": "promotion-approved"
            if decision == "approved"
            else "promotion-rejected",
            "patternId": pattern["patternId"],
            "proposalSha256": proposal["proposalSha256"],
            "actor": actor,
            "occurredAt": self.clock(),
            "reason": reason,
        }
        if decision == "rejected":
            catalog["events"].append(event)
            self._write_catalog_cas(catalog, base_catalog_hash)
            return event
        self._validate_semver(
            catalog, pattern, str(proposal.get("changeType") or "major")
        )
        target: Path | None = None
        if proposal.get("kit"):
            target = self._publish_kit(proposal["kit"], pattern)
            event.update(
                {"manifestSha256": proposed_manifest, "publishedPath": str(target)}
            )
        pattern["promotionEventId"] = event["eventId"]
        catalog["patterns"].append(pattern)
        catalog["events"].append(event)
        try:
            self._write_catalog_cas(catalog, base_catalog_hash)
        except Exception:
            if target is not None:
                shutil.rmtree(target, ignore_errors=True)
            raise
        return event

    def _version_path(self, pattern: dict[str, Any]) -> Path:
        return (
            self.path.parent
            / "hyperframes"
            / str(pattern.get("kitId") or pattern["patternId"])
            / "versions"
            / pattern["version"]
        )

    def _publish_kit(self, kit: dict[str, Any], pattern: dict[str, Any]) -> Path:
        target = self._version_path(pattern)
        stage = target.parent / f".{target.name}.{uuid4().hex}.staging"
        if target.exists():
            raise AnimationError("immutable semantic version directory already exists")
        try:
            stage.mkdir(parents=True)
            for item in kit["files"]:
                path = (stage / item["path"]).resolve()
                try:
                    path.relative_to(stage.resolve())
                except ValueError as exc:
                    raise AnimationError("kit file escaped version directory") from exc
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(item["content"], encoding="utf-8", newline="\n")
                if file_fingerprint(path)["sha256"] != item["sha256"]:
                    raise AnimationError("staged kit fingerprint mismatch")
            atomic_write_json(stage / "manifest.json", kit["manifest"])
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.replace(target)
            return target
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    @staticmethod
    def _validate_semver(
        catalog: dict[str, Any], pattern: dict[str, Any], change_type: str
    ) -> None:
        previous = [
            item
            for item in catalog["patterns"]
            if item["patternId"] == pattern["patternId"]
        ]
        if not previous:
            return
        latest, current = (
            max(_semver(item["version"]) for item in previous),
            _semver(pattern["version"]),
        )
        valid = {
            "major": current[0] > latest[0],
            "minor": current[0] == latest[0] and current[1] > latest[1],
            "patch": current[:2] == latest[:2] and current[2] > latest[2],
        }
        if current <= latest or change_type not in valid or not valid[change_type]:
            raise AnimationError(
                f"semantic version does not match {change_type} change"
            )

    def _check_cas(self, catalog: dict[str, Any], expected: str | None) -> None:
        if expected is not None and content_hash(catalog) != expected:
            raise AnimationError("catalog compare-and-swap failed")

    def _write_catalog_cas(self, value: dict[str, Any], expected: str) -> None:
        current = json.loads(self.path.read_text(encoding="utf-8"))
        if content_hash(current) != expected:
            raise AnimationError("catalog compare-and-swap failed")
        atomic_write_json(self.path, value)

    def resolve_version(
        self, kit_id: str, version: str, *, upgrade_to: str | None = None
    ) -> dict[str, Any]:
        if upgrade_to is not None:
            raise AnimationError(
                "provider animation upgrade requires explicit opt-in instance creation"
            )
        item = next(
            (
                entry
                for entry in self.load()["patterns"]
                if (entry.get("kitId") or entry["patternId"]) == kit_id
                and entry["version"] == version
            ),
            None,
        )
        if item is None:
            raise AnimationError("provider animation version not found")
        result = deepcopy(item)
        if any(
            event["type"] == "version-deprecated"
            and event["patternId"] == result["patternId"]
            and event.get("version") == version
            for event in self.load()["events"]
        ):
            result["status"] = "deprecated"
        return result

    def deprecate(
        self, kit_id: str, version: str, *, actor: str, reason: str
    ) -> dict[str, Any]:
        catalog = self.load()
        item = next(
            (
                entry
                for entry in catalog["patterns"]
                if (entry.get("kitId") or entry["patternId"]) == kit_id
                and entry["version"] == version
            ),
            None,
        )
        if item is None:
            raise AnimationError("provider animation version not found")
        base_catalog_hash = content_hash(catalog)
        event = {
            "eventId": f"animation-event-{len(catalog['events']) + 1:04d}",
            "type": "version-deprecated",
            "patternId": item["patternId"],
            "version": version,
            "proposalSha256": (item.get("manifest") or {}).get("sha256", "0" * 64),
            "actor": actor,
            "occurredAt": self.clock(),
            "reason": reason,
        }
        catalog["events"].append(event)
        self._write_catalog_cas(catalog, base_catalog_hash)
        return event

    def reject_recommendation(
        self,
        *,
        pattern_id: str,
        evidence_sha256: str,
        actor: str,
        reason: str,
        expected_catalog_sha256: str | None = None,
    ) -> dict[str, Any]:
        catalog = self.initialize()
        base_catalog_hash = content_hash(catalog)
        self._check_cas(catalog, expected_catalog_sha256)
        event = {
            "eventId": f"animation-event-{len(catalog['events']) + 1:04d}",
            "type": "recommendation-rejected",
            "patternId": pattern_id,
            "proposalSha256": evidence_sha256,
            "evidenceSha256": evidence_sha256,
            "actor": actor,
            "occurredAt": self.clock(),
            "reason": reason,
        }
        catalog["events"].append(event)
        self._write_catalog_cas(catalog, base_catalog_hash)
        return event


def _semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if not match:
        raise AnimationError("invalid semantic version")
    return tuple(int(part) for part in match.groups())


def _looks_absolute(value: str) -> bool:
    return Path(value).is_absolute() or bool(
        re.search(
            r"(?:^|['\"])(?:[A-Za-z]:[\\/]|file://|/(?:Users|home|mnt|private|tmp)/)",
            value,
            re.IGNORECASE,
        )
    )


def _string_leaves(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_leaves(child)
