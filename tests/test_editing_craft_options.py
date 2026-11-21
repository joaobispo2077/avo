"""Selected craft options preserve scoped intent without starting production."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo import editing_craft
from avo.editing_craft import (
    EditingCraftError,
    inspect_editing_craft,
    reset_editing_craft_preference,
    resolve_editing_craft_selection,
    set_editing_craft_preference,
    validate_editing_craft_selection,
)
from avo.timeline.contracts import ContractError, validate_document


def _put(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


@pytest.fixture
def context(tmp_path):
    root, home, raw = (tmp_path / name for name in ("repository", "user", "footage"))
    raw.mkdir()
    project = raw / "avo.project.json"
    provider = root / "providers/sample/avo.provider.json"
    _put(project, {"provider": "sample", "rawDir": str(raw), "title": "Keep title"})
    _put(
        provider,
        {
            "name": "sample",
            "displayName": "Sample",
            "kind": "youtube",
            "media": {"rawRoot": str(raw.parent)},
        },
    )
    return SimpleNamespace(
        root=root,
        home=home,
        raw=raw,
        project=project,
        provider=provider,
        preferences=home / ".avo/preferences.json",
    )


def _inspect(context, **kwargs):
    return inspect_editing_craft(
        context.project, root=context.root, home=context.home, **kwargs
    )


def test_defaults_are_static_and_have_no_map_enablement_choice():
    selection = resolve_editing_craft_selection()
    effective = selection["effective"]
    assert effective["camera"]["enabled"] is False
    assert effective["camera"]["faceAnchor"] == "off"
    assert effective["soundMatching"] == {
        "enabled": False,
        "mode": "descriptor",
        "allowLayering": False,
    }
    assert effective["referenceAnalysis"]["enabled"] is False
    assert effective["spokenNotes"]["enabled"] is False
    assert effective["speechRecovery"]["enabled"] is False
    assert effective["speechRecovery"]["maxAttemptsPerInterval"] == 1
    assert effective["handoff"]["mode"] == "none"
    assert "enableMotionMap" not in effective
    assert validate_editing_craft_selection(selection) == selection


def test_repetition_window_is_optional_and_retains_precedence_and_provenance():
    selection = resolve_editing_craft_selection(
        provider_settings={"soundMatching": {"repetitionWindowMs": 3000}},
        invocation={"soundMatching": {"enabled": True, "repetitionWindowMs": 0}},
    )
    assert selection["effective"]["soundMatching"]["repetitionWindowMs"] == 0
    assert selection["sources"]["soundMatching.repetitionWindowMs"] == "invocation"
    assert selection["maskedChoices"] == [
        {
            "path": "soundMatching.repetitionWindowMs",
            "value": 3000,
            "source": "provider",
            "maskedBy": "invocation",
        }
    ]
    assert (
        "repetitionWindowMs"
        not in resolve_editing_craft_selection()["effective"]["soundMatching"]
    )


@pytest.mark.parametrize(
    ("scope", "source"),
    [
        ("global_settings", "global"),
        ("provider_settings", "provider"),
        ("video_defaults", "video-defaults"),
        ("project_settings", "project"),
        ("invocation", "invocation"),
    ],
)
def test_explicit_false_is_preserved_at_each_scope(scope, source):
    selection = resolve_editing_craft_selection(
        **{scope: {"camera": {"enabled": False}}}
    )
    assert selection["effective"]["camera"]["enabled"] is False
    assert selection["sources"]["camera.enabled"] == source


def test_all_scopes_merge_per_leaf_and_keep_masked_values():
    selection = resolve_editing_craft_selection(
        global_settings={"camera": {"enabled": True, "baseTreatment": "alternate"}},
        provider_settings={"camera": {"baseTreatment": "push"}},
        video_defaults={"camera": {"onLost": "hold"}},
        project_settings={"camera": {"enabled": False}},
        invocation={"reviewPresentation": "text"},
    )
    assert selection["effective"]["camera"] == {
        "enabled": False,
        "baseTreatment": "push",
        "faceAnchor": "off",
        "onLost": "hold",
    }
    assert selection["sources"]["camera.onLost"] == "video-defaults"
    assert {item["source"] for item in selection["maskedChoices"]} == {
        "global",
    }
    assert any(
        item["path"] == "camera.baseTreatment" for item in selection["inactiveChoices"]
    )


@pytest.mark.parametrize(
    "scope",
    ["global_settings", "provider_settings", "video_defaults", "project_settings"],
)
@pytest.mark.parametrize(
    "invalid",
    [
        {"camera": {"enabled": "false"}},
        {"camera": {"faceAnchor": "largest-face"}},
        {"enableMotionMap": True},
        {"soundMatching": None},
        {"contractVersion": "9.0.0"},
        {"speechRecovery": {"maxAttemptsPerInterval": 0}},
    ],
)
def test_invalid_masked_scope_never_silently_falls_through(scope, invalid):
    with pytest.raises(EditingCraftError):
        resolve_editing_craft_selection(
            **{scope: invalid}, invocation={"camera": {"enabled": False}}
        )


def test_face_choice_remains_visible_but_inactive_when_camera_disabled():
    selected = resolve_editing_craft_selection(
        invocation={"camera": {"faceAnchor": "selected-subject"}}
    )
    assert selected["effective"]["camera"]["faceAnchor"] == "selected-subject"
    assert selected["inactiveChoices"] == [
        {
            "path": "camera.faceAnchor",
            "value": "selected-subject",
            "source": "invocation",
            "reason": "camera-disabled",
        }
    ]


def test_selection_hash_retains_provenance_and_detects_tampering():
    implicit = resolve_editing_craft_selection()
    explicit = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": False}}
    )
    assert implicit["effective"] == explicit["effective"]
    assert implicit["selectionHash"] != explicit["selectionHash"]
    tampered = deepcopy(explicit)
    tampered["effective"]["camera"]["enabled"] = True
    with pytest.raises(EditingCraftError, match="hash"):
        validate_editing_craft_selection(tampered)


def test_resolving_future_preferences_does_not_mutate_frozen_selection():
    settings = {"camera": {"enabled": True}}
    recorded = resolve_editing_craft_selection(project_settings=settings)
    unchanged = deepcopy(recorded)
    settings["camera"]["enabled"] = False
    future = resolve_editing_craft_selection(project_settings=settings)
    future["effective"]["camera"]["onLost"] = "static"
    assert recorded == unchanged
    assert (
        resolve_editing_craft_selection()["effective"]["camera"]["onLost"] == "review"
    )


def test_inspection_is_read_only_and_does_not_inspect_optional_runtime(
    context, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("optional motion/runtime inspection was started")

    monkeypatch.setattr("avo.motion.inspect_motion", forbidden)
    before = sorted(
        str(path.relative_to(context.root.parent))
        for path in context.root.parent.rglob("*")
    )
    shown = _inspect(context)
    after = sorted(
        str(path.relative_to(context.root.parent))
        for path in context.root.parent.rglob("*")
    )
    assert before == after
    assert shown["builtIn"] == {"motionMap": True, "storyboard": True}
    assert shown["documents"]["global"]["sha256"] == "absent"
    assert not (context.raw / "edit").exists()


def test_video_default_is_not_relabeled_project_and_invalid_default_is_rejected(
    context,
):
    registry = context.root / "providers/sample/videos/example/video.json"
    document = {
        "id": "example",
        "provider": "sample",
        "rawDir": str(context.raw),
        "status": "in-progress",
        "createdAt": "2026-11-16",
        "defaults": {"editingCraft": {"camera": {"baseTreatment": "push"}}},
    }
    _put(registry, document)
    assert (
        _inspect(context)["selection"]["sources"]["camera.baseTreatment"]
        == "video-defaults"
    )
    document["defaults"]["editingCraft"]["camera"]["baseTreatment"] = "invalid"
    _put(registry, document)
    with pytest.raises(EditingCraftError):
        _inspect(context, invocation={"camera": {"baseTreatment": "none"}})


@pytest.mark.parametrize("scope", ["global", "provider", "project"])
def test_preference_write_requires_expected_bytes_and_preserves_other_fields(
    context, scope
):
    target = {
        "global": context.preferences,
        "provider": context.provider,
        "project": context.project,
    }[scope]
    if scope == "global":
        _put(
            target,
            {
                "schemaVersion": "1.0.0",
                "motion": {"engine": "code-drawn"},
                "other": "retain",
            },
        )
    original = _read(target)
    changed = set_editing_craft_preference(
        scope=scope,
        patch={"camera": {"enabled": True}},
        expected_document=_digest(target),
        project=context.project,
        provider="sample",
        root=context.root,
        home=context.home,
    )
    assert changed["before"] != changed["after"]
    assert changed["after"] == _digest(target)
    reset_editing_craft_preference(
        scope=scope,
        expected_document=_digest(target),
        project=context.project,
        provider="sample",
        root=context.root,
        home=context.home,
    )
    assert _read(target) == original


def test_write_rejects_stale_expected_document_and_other_provider(context):
    expected = _digest(context.project)
    current = _read(context.project)
    current["title"] = "New creator change"
    _put(context.project, current)
    for provider, identity in [
        ("sample", expected),
        ("different", _digest(context.project)),
    ]:
        with pytest.raises(EditingCraftError):
            set_editing_craft_preference(
                scope="project",
                patch={"camera": {"enabled": True}},
                expected_document=identity,
                project=context.project,
                provider=provider,
                root=context.root,
                home=context.home,
            )
    assert _read(context.project) == current


def test_first_global_write_and_partial_patch_are_supported(context):
    set_editing_craft_preference(
        scope="global",
        patch={"camera": {"enabled": True, "onLost": "hold"}},
        expected_document="absent",
        root=context.root,
        home=context.home,
    )
    set_editing_craft_preference(
        scope="global",
        patch={"camera": {"enabled": False}},
        expected_document=_digest(context.preferences),
        root=context.root,
        home=context.home,
    )
    camera = _inspect(context)["selection"]["effective"]["camera"]
    assert camera["enabled"] is False
    assert camera["onLost"] == "hold"


def test_reset_absent_preferences_is_a_byte_preserving_noop(context):
    result = reset_editing_craft_preference(
        scope="global", expected_document="absent", root=context.root, home=context.home
    )
    assert not context.preferences.exists()
    assert result["before"] == result["after"] == "absent"


def test_write_race_keeps_the_newer_document(context, monkeypatch):
    expected = _digest(context.project)
    original_save = editing_craft._save_motion_candidate
    newer = {**_read(context.project), "title": "Keep concurrent creator title"}

    def changed_before_save(target, original_bytes, candidate, scope, root):
        _put(target, newer)
        return original_save(target, original_bytes, candidate, scope, root)

    monkeypatch.setattr(editing_craft, "_save_motion_candidate", changed_before_save)
    with pytest.raises(EditingCraftError, match="concurrently"):
        set_editing_craft_preference(
            scope="project",
            patch={"camera": {"enabled": True}},
            expected_document=expected,
            project=context.project,
            root=context.root,
            home=context.home,
        )
    assert _read(context.project) == newer


def test_post_commit_race_never_reports_our_selection_with_another_hash(
    context, monkeypatch
):
    original_save = editing_craft._save_motion_candidate
    newer = {**_read(context.project), "title": "Creator changed after our save"}

    def changed_after_save(target, original_bytes, candidate, scope, root):
        original_save(target, original_bytes, candidate, scope, root)
        _put(target, newer)

    monkeypatch.setattr(editing_craft, "_save_motion_candidate", changed_after_save)
    with pytest.raises(EditingCraftError) as failure:
        set_editing_craft_preference(
            scope="project",
            patch={"camera": {"enabled": True}},
            expected_document=_digest(context.project),
            project=context.project,
            root=context.root,
            home=context.home,
        )
    assert failure.value.code == "CRAFT_DOCUMENT_CHANGED"
    assert _read(context.project) == newer


@pytest.mark.parametrize("owner", ["global", "provider", "project", "video"])
def test_owner_schemas_reject_unknown_craft_keys(context, owner):
    invalid = {"camera": {"automaticEveryCut": True}}
    if owner == "global":
        value, schema = (
            {"schemaVersion": "1.0.0", "editingCraft": invalid},
            "avo.motion.schema.json",
        )
    elif owner == "provider":
        value = {
            **_read(context.provider),
            "routingOverrides": {"editingCraft": invalid},
        }
        schema = str(editing_craft.repo_root() / "providers/avo.provider.schema.json")
    elif owner == "project":
        value, schema = (
            {**_read(context.project), "editingCraft": invalid},
            "avo.project.schema.json",
        )
    else:
        value = {
            "id": "sample",
            "provider": "sample",
            "rawDir": str(context.raw),
            "status": "in-progress",
            "createdAt": "2026-11-16",
            "defaults": {"editingCraft": invalid},
        }
        schema = "avo.video.schema.json"
    with pytest.raises(ContractError):
        validate_document(value, schema)
