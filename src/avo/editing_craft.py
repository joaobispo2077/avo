"""Scoped craft choices and guarded preference writes, without media execution."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from avo.motion import (
    MotionError,
    _motion_documents,
    _save_motion_candidate,
    _validate_motion_write_target,
)
from avo.paths import repo_root
from avo.settings import resolve_scoped_settings, stable_settings_hash
from avo.timeline.contracts import ContractError, validate_document

DEFAULTS = {
    "contractVersion": "1.0.0",
    "camera": {
        "enabled": False,
        "baseTreatment": "none",
        "faceAnchor": "off",
        "onLost": "review",
    },
    "soundMatching": {"enabled": False, "mode": "descriptor", "allowLayering": False},
    "referenceAnalysis": {"enabled": False},
    "spokenNotes": {"enabled": False},
    "speechRecovery": {
        "enabled": False,
        "maxAttemptsPerInterval": 1,
        "maxIntervalSeconds": 30,
        "maxTotalSeconds": 120,
    },
    "handoff": {"mode": "none"},
    "reviewPresentation": "both",
}


class EditingCraftError(ValueError):
    """A typed selection, source-document or preference-write failure."""

    def __init__(
        self, code, message, *, field="", remediation="Repair the input and retry."
    ):
        super().__init__(message)
        self.code = code
        self.field = field
        self.remediation = remediation

    def to_dict(self):
        return {
            "code": self.code,
            "message": str(self),
            "field": self.field,
            "remediation": self.remediation,
            "blocking": True,
        }


def _validate(value, definition):
    try:
        validate_document(value, f"avo.editing-craft.schema.json#/$defs/{definition}")
    except ContractError as error:
        raise EditingCraftError("CRAFT_CONFIG_INVALID", str(error)) from error


def validate_editing_craft_config(value):
    """Validate a partial scope before precedence can mask invalid input."""
    _validate(value, "config")
    return deepcopy(value)


def _leaves(value, prefix=""):
    leaves = {}
    for key in sorted(value):
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value[key], dict):
            leaves.update(_leaves(value[key], path))
        else:
            leaves[path] = value[key]
    return leaves


def _inactive_choices(effective, sources):
    choices = []
    for branch in (
        "camera",
        "soundMatching",
        "referenceAnalysis",
        "spokenNotes",
        "speechRecovery",
    ):
        if effective[branch]["enabled"]:
            continue
        for path, value in _leaves(effective[branch], branch).items():
            if path.endswith(".enabled") or sources[path] == "default":
                continue
            choices.append(
                {
                    "path": path,
                    "value": value,
                    "source": sources[path],
                    "reason": f"{branch}-disabled",
                }
            )
    if (
        "targetProfile" in effective["handoff"]
        and effective["handoff"]["mode"] != "editor"
    ):
        path = "handoff.targetProfile"
        choices.append(
            {
                "path": path,
                "value": effective["handoff"]["targetProfile"],
                "source": sources[path],
                "reason": "editor-handoff-not-selected",
            }
        )
    return choices


def _selection(scopes):
    resolved = resolve_scoped_settings(defaults=deepcopy(DEFAULTS), scopes=scopes)
    _validate(resolved.values, "effective")
    sources = {path: resolved.sources[path] for path in _leaves(resolved.values)}
    masked = [
        {"path": path, "value": value, "source": source, "maskedBy": sources[path]}
        for source, patch in scopes
        for path, value in _leaves(patch or {}).items()
        if source != sources[path]
    ]
    result = {
        "contractVersion": "1.0.0",
        "effective": resolved.values,
        "sources": sources,
        "maskedChoices": masked,
        "inactiveChoices": _inactive_choices(resolved.values, sources),
    }
    result["selectionHash"] = stable_settings_hash(result)
    return validate_editing_craft_selection(result)


def resolve_editing_craft_selection(
    *,
    global_settings=None,
    provider_settings=None,
    video_defaults=None,
    project_settings=None,
    invocation=None,
):
    """Resolve typed partial scopes with explicit false and per-leaf provenance."""
    scopes = [
        ("global", global_settings),
        ("provider", provider_settings),
        ("video-defaults", video_defaults),
        ("project", project_settings),
        ("invocation", invocation),
    ]
    validated = [
        (name, validate_editing_craft_config(value) if value is not None else None)
        for name, value in scopes
    ]
    return _selection(validated)


def validate_editing_craft_selection(selection):
    """Reject malformed or changed frozen selections, including their provenance."""
    _validate(selection, "selection")
    payload = {key: value for key, value in selection.items() if key != "selectionHash"}
    if stable_settings_hash(payload) != selection["selectionHash"]:
        raise EditingCraftError(
            "CRAFT_SELECTION_INVALID", "Craft selection hash differs from its payload"
        )
    if set(selection["sources"]) != set(_leaves(selection["effective"])):
        raise EditingCraftError(
            "CRAFT_SELECTION_INVALID",
            "Craft selection sources differ from effective leaves",
        )
    return deepcopy(selection)


def _parent(document, scope):
    return document.get("routingOverrides", {}) if scope == "provider" else document


def _document_identity(raw):
    return "absent" if raw is None else hashlib.sha256(raw).hexdigest()


def _documents(project, provider, root, home):
    try:
        return _motion_documents(
            project=project, provider=provider, root=root, home=home
        )
    except MotionError as error:
        raise EditingCraftError(
            "CRAFT_TARGET_INVALID", str(error), field=error.field
        ) from error


def _video_defaults(documents, root):
    from avo.video_registry import find_video_by_raw_dir

    path, project, _ = documents["project"]
    if path is None:
        return None
    registry = find_video_by_raw_dir(
        path.parent, provider=project["provider"], root=root
    )
    return ((registry or {}).get("defaults") or {}).get("editingCraft")


def _inspection(documents, root, invocation=None):
    settings = {
        f"{scope}_settings": _parent(document, scope).get("editingCraft")
        for scope, (_, document, _) in documents.items()
    }
    selected = resolve_editing_craft_selection(
        **settings,
        video_defaults=_video_defaults(documents, root),
        invocation=invocation,
    )
    return {
        "contractVersion": "1.0.0",
        "operation": "options-show",
        "selection": selected,
        "documents": {
            scope: {
                "path": str(path) if path is not None else None,
                "sha256": _document_identity(raw),
            }
            for scope, (path, _, raw) in documents.items()
        },
        "builtIn": {"motionMap": True, "storyboard": True},
    }


def inspect_editing_craft(
    project=None, provider=None, *, root=None, home=None, invocation=None
):
    """Inspect metadata only; never open timeline stores or optional runtimes."""
    root = repo_root(root)
    home = Path(home) if home is not None else Path.home()
    return _inspection(_documents(project, provider, root, home), root, invocation)


def _candidate(original, scope, patch):
    candidate = deepcopy(original)
    parent = (
        candidate.setdefault("routingOverrides", {})
        if scope == "provider"
        else candidate
    )
    if patch is None:
        parent.pop("editingCraft", None)
        if scope == "provider" and not parent:
            candidate.pop("routingOverrides", None)
    else:
        old = validate_editing_craft_config(parent.get("editingCraft", {}))
        parent["editingCraft"] = resolve_scoped_settings(
            defaults=old, scopes=[("patch", patch)]
        ).values
    return candidate


def _matches_candidate(raw, candidate):
    try:
        return json.loads(raw) == candidate
    except (TypeError, ValueError, UnicodeDecodeError):
        return False


def _save_preference(target, original, original_bytes, candidate, scope, root):
    try:
        if candidate != original:
            _save_motion_candidate(target, original_bytes, candidate, scope, root)
        observed = target.read_bytes() if target.exists() else None
    except (MotionError, OSError) as error:
        raise EditingCraftError("CRAFT_WRITE_FAILED", str(error)) from error
    if candidate == original and observed != original_bytes:
        raise EditingCraftError(
            "CRAFT_DOCUMENT_CHANGED", "Preference target changed concurrently"
        )
    if candidate != original and not _matches_candidate(observed, candidate):
        raise EditingCraftError(
            "CRAFT_DOCUMENT_CHANGED", "Preference target changed after publication"
        )
    return _document_identity(observed)


def _replace(scope, patch, expected_document, project, provider, root, home):
    try:
        _validate_motion_write_target(scope, project, provider)
    except MotionError as error:
        raise EditingCraftError("CRAFT_SCOPE_REQUIRED", str(error)) from error
    if not isinstance(expected_document, str) or not re.fullmatch(
        r"absent|[a-f0-9]{64}", expected_document
    ):
        raise EditingCraftError(
            "CRAFT_DOCUMENT_INVALID", "Expected exact document SHA-256 or absent"
        )
    root = repo_root(root)
    documents = _documents(
        project, provider, root, Path(home) if home is not None else Path.home()
    )
    target, original, original_bytes = documents[scope]
    if target is None or _document_identity(original_bytes) != expected_document:
        raise EditingCraftError(
            "CRAFT_DOCUMENT_CHANGED", "Preference target differs from expected document"
        )
    candidate = _candidate(original, scope, patch)
    proposed = {**documents, scope: (target, candidate, original_bytes)}
    result = _inspection(proposed, root)
    after = _save_preference(target, original, original_bytes, candidate, scope, root)
    result["documents"][scope]["sha256"] = after
    return {
        **result,
        "operation": "options-reset" if patch is None else "options-set",
        "scope": scope,
        "before": expected_document,
        "after": after,
    }


def set_editing_craft_preference(
    *,
    scope,
    patch,
    expected_document,
    project=None,
    provider=None,
    root=None,
    home=None,
):
    """Patch one exact selected preference scope without changing an active edit."""
    patch = validate_editing_craft_config(patch)
    if not patch:
        raise EditingCraftError(
            "CRAFT_CONFIG_INVALID", "Preference patch must not be empty"
        )
    return _replace(scope, patch, expected_document, project, provider, root, home)


def reset_editing_craft_preference(
    *, scope, expected_document, project=None, provider=None, root=None, home=None
):
    """Remove only this scope's craft options so future requests inherit again."""
    return _replace(scope, None, expected_document, project, provider, root, home)
