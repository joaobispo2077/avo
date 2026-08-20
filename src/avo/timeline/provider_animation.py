"""Explicit sanitized provider animation proposal and promotion service."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .animation import AnimationError, _keys
from .contracts import content_hash, validate_document
from .store import atomic_write_json, now_iso

FORBIDDEN_FIELDS = {
    "text",
    "timestamps",
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


class ProviderAnimationService:
    def __init__(
        self,
        catalog_path: Path,
        *,
        provider: str,
        clock: Callable[[], str] = now_iso,
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
            if Path(leaf).is_absolute() or re.search(
                r"\.(mp4|mov|mkv|png|jpe?g|webp|avif)$", leaf, re.IGNORECASE
            ):
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
        return value

    def propose(
        self, pattern: dict[str, Any], *, actor: str, intent_reference: str
    ) -> dict[str, Any]:
        if not actor or not intent_reference:
            raise AnimationError("explicit creator promotion intent is required")
        sanitized = self.sanitize(pattern)
        proposal = {
            "schemaVersion": "1.0.0",
            "provider": self.provider,
            "pattern": sanitized,
            "actor": actor,
            "intentReference": intent_reference,
            "createdAt": self.clock(),
        }
        proposal["proposalSha256"] = content_hash(proposal)
        path = (
            self.path.parent
            / "proposals"
            / f"{sanitized['patternId']}-{proposal['proposalSha256'][:12]}.json"
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
        catalog["events"].append(event)
        if decision == "approved":
            if any(
                item["patternId"] == pattern["patternId"]
                for item in catalog["patterns"]
            ):
                raise AnimationError("provider pattern ID already exists")
            pattern["promotionEventId"] = event["eventId"]
            catalog["patterns"].append(pattern)
        atomic_write_json(self.path, catalog)
        return event

    def reject_recommendation(
        self,
        *,
        pattern_id: str,
        evidence_sha256: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        catalog = self.initialize()
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
        atomic_write_json(self.path, catalog)
        return event


def _string_leaves(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_leaves(child)
