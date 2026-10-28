"""Scope, persistence and preservation behavior for motion preferences."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import motion
from avo.motion import (
    MotionError,
    inspect_motion,
    reset_motion_preference,
    resolve_motion_selection,
    set_motion_preference,
)

REPO = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def context(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "repository"
    home = tmp_path / "home"
    raw = tmp_path / "footage" / "example-video"
    raw.mkdir(parents=True)
    home.mkdir()
    config = root / "config" / "avo.config.json"
    write_json(config, {"jobs": {"motion": {"local": ["hyperframes", "remotion"]}}})
    provider_schema = root / "providers" / "avo.provider.schema.json"
    provider_schema.parent.mkdir(parents=True)
    shutil.copyfile(REPO / "providers" / "avo.provider.schema.json", provider_schema)
    provider = root / "providers" / "sample" / "avo.provider.json"
    write_json(
        provider,
        {
            "name": "sample",
            "displayName": "Example channel",
            "kind": "youtube",
            "media": {"rawRoot": str(raw.parent)},
            "routingOverrides": {"watch": {"device": "cpu"}},
        },
    )
    project = raw / "avo.project.json"
    write_json(
        project,
        {
            "provider": "sample",
            "rawDir": str(raw),
            "title": "Keep this title",
            "transcription": {"language": "en"},
        },
    )
    return SimpleNamespace(
        root=root,
        home=home,
        raw=raw,
        provider=provider,
        project=project,
        config=config,
        preferences=home / ".avo" / "preferences.json",
    )


@pytest.mark.parametrize(
    ("settings", "engine", "source"),
    [
        ({}, "hyperframes", "default"),
        ({"global_settings": {"engine": "code-drawn"}}, "code-drawn", "global"),
        (
            {
                "global_settings": {"engine": "code-drawn"},
                "provider_settings": {"engine": "remotion"},
            },
            "remotion",
            "provider",
        ),
        (
            {
                "global_settings": {"engine": "code-drawn"},
                "provider_settings": {"engine": "remotion"},
                "project_settings": {"engine": "hyperframes"},
            },
            "hyperframes",
            "project",
        ),
        (
            {
                "global_settings": {"engine": "hyperframes"},
                "provider_settings": {"engine": "remotion"},
                "project_settings": {"engine": "hyperframes"},
                "invocation": {"engine": "code-drawn"},
            },
            "code-drawn",
            "invocation",
        ),
    ],
)
def test_every_stronger_scope_wins(settings: dict, engine: str, source: str) -> None:
    original = deepcopy(settings)
    result = resolve_motion_selection(**settings)
    assert result["engine"] == engine
    assert result["source"] == source
    assert result["advanced"] is (engine == "code-drawn")
    assert len(result["resolutionHash"]) == 64
    assert settings == original


def test_masked_values_and_resolution_identity_retain_provenance() -> None:
    result = resolve_motion_selection(
        global_settings={"engine": "code-drawn"},
        provider_settings={"engine": "remotion"},
        project_settings={"engine": "hyperframes"},
        invocation={"engine": "code-drawn"},
    )
    assert {(item["source"], item["engine"]) for item in result["maskedChoices"]} == {
        ("global", "code-drawn"),
        ("provider", "remotion"),
        ("project", "hyperframes"),
    }
    same = resolve_motion_selection(
        global_settings={"engine": "code-drawn"},
        provider_settings={"engine": "remotion"},
        project_settings={"engine": "hyperframes"},
        invocation={"engine": "code-drawn"},
    )
    assert same == result
    global_only = resolve_motion_selection(global_settings={"engine": "code-drawn"})
    assert global_only["engine"] == result["engine"]
    assert global_only["resolutionHash"] != result["resolutionHash"]


@pytest.mark.parametrize(
    "scope", ["global_settings", "provider_settings", "project_settings", "invocation"]
)
@pytest.mark.parametrize("value", [None, "", "canvas", "none"])
def test_invalid_explicit_choice_never_silently_falls_through(scope, value) -> None:
    settings = {scope: {"engine": value}}
    if scope != "invocation":
        settings["invocation"] = {"engine": "code-drawn"}
    with pytest.raises(MotionError):
        resolve_motion_selection(**settings)


def test_empty_scopes_inherit_without_becoming_explicit() -> None:
    result = resolve_motion_selection(
        global_settings={}, provider_settings={}, project_settings={}, invocation={}
    )
    assert result["engine"] == "hyperframes"
    assert result["source"] == "default"
    assert result["maskedChoices"] == []


def test_global_inspection_is_read_only_and_needs_no_project(context) -> None:
    before = context.config.read_bytes()
    result = inspect_motion(root=context.root, home=context.home)
    assert result["selection"]["engine"] == "hyperframes"
    assert result["selection"]["source"] == "default"
    assert result["savedPreferences"]["global"] == {
        "engine": None,
        "target": str(context.preferences.resolve()),
    }
    assert result["runSelection"] is None
    assert result["recordedAnimation"] is None
    assert not context.preferences.exists()
    assert context.config.read_bytes() == before


def test_global_save_survives_new_inspection_and_preserves_unrelated_data(
    context,
) -> None:
    config_before = context.config.read_bytes()
    write_json(
        context.preferences,
        {"schemaVersion": "1.0.0", "appearance": {"theme": "dark"}, "motion": {}},
    )
    result = set_motion_preference(
        scope="global", engine="code-drawn", root=context.root, home=context.home
    )
    assert result["selection"]["engine"] == "code-drawn"
    assert result["selection"]["source"] == "global"
    saved = read_json(context.preferences)
    assert saved["motion"]["engine"] == "code-drawn"
    assert saved["appearance"] == {"theme": "dark"}
    fresh = inspect_motion(root=context.root, home=context.home)
    assert fresh["selection"]["engine"] == "code-drawn"
    assert fresh["selection"]["resolutionHash"] == result["selection"]["resolutionHash"]
    assert context.config.read_bytes() == config_before


def test_provider_and_project_preferences_affect_only_their_targets(context) -> None:
    set_motion_preference(
        scope="global", engine="hyperframes", root=context.root, home=context.home
    )
    set_motion_preference(
        scope="provider",
        engine="code-drawn",
        provider="sample",
        root=context.root,
        home=context.home,
    )
    result = set_motion_preference(
        scope="project",
        engine="remotion",
        project=context.project,
        root=context.root,
        home=context.home,
    )
    assert result["selection"]["engine"] == "remotion"
    assert result["selection"]["source"] == "project"
    provider = read_json(context.provider)
    assert provider["routingOverrides"]["motion"]["engine"] == "code-drawn"
    assert provider["routingOverrides"]["watch"] == {"device": "cpu"}
    project = read_json(context.project)
    assert project["motion"]["engine"] == "remotion"
    assert project["title"] == "Keep this title"
    assert project["transcription"] == {"language": "en"}

    other = context.root / "providers" / "another" / "avo.provider.json"
    write_json(
        other,
        {
            "name": "another",
            "kind": "youtube",
            "media": {"rawRoot": str(context.raw.parent)},
        },
    )
    inherited = inspect_motion(provider="another", root=context.root, home=context.home)
    assert inherited["selection"]["engine"] == "hyperframes"
    assert inherited["selection"]["source"] == "global"


def test_run_override_is_disclosed_without_persisting_it(context) -> None:
    set_motion_preference(
        scope="project",
        engine="hyperframes",
        project=context.project,
        root=context.root,
        home=context.home,
    )
    before = context.project.read_bytes()
    override = inspect_motion(
        project=context.project,
        invocation="code-drawn",
        root=context.root,
        home=context.home,
    )
    assert override["selection"]["engine"] == "code-drawn"
    assert override["selection"]["source"] == "invocation"
    assert context.project.read_bytes() == before
    fresh = inspect_motion(
        project=context.project, root=context.root, home=context.home
    )
    assert fresh["selection"]["engine"] == "hyperframes"
    assert fresh["selection"]["source"] == "project"
    assert not context.preferences.exists()


def test_reset_removes_only_that_scope_leaf_then_restores_inheritance(context) -> None:
    set_motion_preference(
        scope="global", engine="hyperframes", root=context.root, home=context.home
    )
    set_motion_preference(
        scope="provider",
        engine="remotion",
        provider="sample",
        root=context.root,
        home=context.home,
    )
    set_motion_preference(
        scope="project",
        engine="code-drawn",
        project=context.project,
        root=context.root,
        home=context.home,
    )
    result = reset_motion_preference(
        scope="project", project=context.project, root=context.root, home=context.home
    )
    assert result["selection"]["engine"] == "remotion"
    assert result["selection"]["source"] == "provider"
    assert "engine" not in read_json(context.project).get("motion", {})
    assert read_json(context.project)["title"] == "Keep this title"
    result = reset_motion_preference(
        scope="provider", provider="sample", root=context.root, home=context.home
    )
    assert result["selection"]["engine"] == "hyperframes"
    assert result["selection"]["source"] == "global"
    assert read_json(context.provider)["routingOverrides"]["watch"] == {"device": "cpu"}
    result = reset_motion_preference(
        scope="global", root=context.root, home=context.home
    )
    assert result["selection"]["source"] == "default"


def test_absent_global_reset_is_idempotent_and_does_not_create_a_file(context) -> None:
    for _ in range(2):
        result = reset_motion_preference(
            scope="global", root=context.root, home=context.home
        )
        assert result["selection"]["source"] == "default"
    assert not context.preferences.exists()


def test_saving_unavailable_remotion_is_not_automatic_fallback(context) -> None:
    result = set_motion_preference(
        scope="global", engine="remotion", root=context.root, home=context.home
    )
    assert result["selection"]["engine"] == "remotion"
    assert read_json(context.preferences)["motion"]["engine"] == "remotion"
    inspected = inspect_motion(root=context.root, home=context.home, operation="render")
    assert inspected["selection"]["engine"] == "remotion"
    assert inspected["readiness"]["ready"] is False
    assert inspected["readiness"]["state"] in {"unavailable", "unsupported"}
    assert inspected["readiness"]["blockers"]
    assert inspected["readiness"]["nextActions"]


@pytest.mark.parametrize("scope", ["provider", "project", "missing"])
def test_missing_or_unknown_scope_target_does_not_broaden_a_write(
    context, scope
) -> None:
    before = {path: path.read_bytes() for path in (context.provider, context.project)}
    with pytest.raises(MotionError):
        set_motion_preference(
            scope=scope, engine="code-drawn", root=context.root, home=context.home
        )
    assert not context.preferences.exists()
    assert all(path.read_bytes() == data for path, data in before.items())


def test_invalid_engine_preserves_an_existing_preference(context) -> None:
    write_json(
        context.preferences,
        {"schemaVersion": "1.0.0", "motion": {"engine": "hyperframes"}},
    )
    before = context.preferences.read_bytes()
    with pytest.raises(MotionError):
        set_motion_preference(
            scope="global", engine="none", root=context.root, home=context.home
        )
    assert context.preferences.read_bytes() == before


@pytest.mark.parametrize(
    "payload",
    ["{invalid", "[]", '{"schemaVersion":"0.0.0","motion":{"engine":"hyperframes"}}'],
)
def test_malformed_existing_global_data_is_not_replaced_or_ignored(
    context, payload
) -> None:
    context.preferences.parent.mkdir(parents=True)
    context.preferences.write_text(payload, encoding="utf-8")
    before = context.preferences.read_bytes()
    with pytest.raises(MotionError):
        inspect_motion(root=context.root, home=context.home)
    with pytest.raises(MotionError):
        set_motion_preference(
            scope="global", engine="code-drawn", root=context.root, home=context.home
        )
    assert context.preferences.read_bytes() == before


def test_provider_name_and_project_provider_must_match_explicit_target(context) -> None:
    document = read_json(context.provider)
    document["name"] = "different-channel"
    write_json(context.provider, document)
    before = context.provider.read_bytes()
    with pytest.raises(MotionError):
        set_motion_preference(
            scope="provider",
            engine="code-drawn",
            provider="sample",
            root=context.root,
            home=context.home,
        )
    assert context.provider.read_bytes() == before
    before = context.project.read_bytes()
    with pytest.raises(MotionError):
        set_motion_preference(
            scope="project",
            engine="code-drawn",
            project=context.project,
            provider="another",
            root=context.root,
            home=context.home,
        )
    assert context.project.read_bytes() == before


def test_project_raw_directory_mismatch_preserves_original_document(context) -> None:
    document = read_json(context.project)
    document["rawDir"] = str(context.raw.parent / "different-video")
    write_json(context.project, document)
    before = context.project.read_bytes()
    with pytest.raises(MotionError):
        set_motion_preference(
            scope="project",
            engine="code-drawn",
            project=context.project,
            root=context.root,
            home=context.home,
        )
    assert context.project.read_bytes() == before


def test_atomic_replace_failure_leaves_original_bytes(context, monkeypatch) -> None:
    write_json(
        context.preferences,
        {"schemaVersion": "1.0.0", "motion": {"engine": "hyperframes"}},
    )
    before = context.preferences.read_bytes()
    original_replace = Path.replace

    def fail_preference_replace(path, target):
        if Path(target).resolve() == context.preferences.resolve():
            raise PermissionError("preference replacement denied")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_preference_replace)
    with pytest.raises(MotionError) as caught:
        set_motion_preference(
            scope="global", engine="code-drawn", root=context.root, home=context.home
        )
    assert caught.value.code == "MOTION_WRITE_FAILED"
    assert context.preferences.read_bytes() == before


def test_competing_edit_is_detected_without_losing_other_writer_data(
    context, monkeypatch
) -> None:
    write_json(
        context.preferences,
        {"schemaVersion": "1.0.0", "motion": {"engine": "hyperframes"}},
    )
    competing = {
        "schemaVersion": "1.0.0",
        "motion": {"engine": "hyperframes"},
        "concurrent": {"owner": "another-writer"},
    }
    original_validate = motion.validate_motion_config
    changed = False

    def validate_and_edit(value):
        nonlocal changed
        result = original_validate(value)
        if not changed and value == {"engine": "hyperframes"}:
            changed = True
            write_json(context.preferences, competing)
        return result

    monkeypatch.setattr(motion, "validate_motion_config", validate_and_edit)
    with pytest.raises(MotionError) as caught:
        set_motion_preference(
            scope="global", engine="code-drawn", root=context.root, home=context.home
        )
    assert changed, "The competing edit must occur after the original setting is read."
    assert caught.value.code == "MOTION_CONFIG_CHANGED"
    assert read_json(context.preferences) == competing


def test_missing_inferred_provider_preserves_project_and_global_inheritance(context):
    context.provider.unlink()
    set_motion_preference(
        scope="global", engine="code-drawn", root=context.root, home=context.home
    )
    before = context.project.read_bytes()
    shown = inspect_motion(
        project=context.project, root=context.root, home=context.home
    )
    assert shown["selection"]["engine"] == "code-drawn"
    assert shown["selection"]["source"] == "global"
    assert shown["savedPreferences"]["provider"]["engine"] is None
    assert context.project.read_bytes() == before
    assert not context.provider.exists()
    saved = set_motion_preference(
        scope="project",
        engine="hyperframes",
        project=context.project,
        root=context.root,
        home=context.home,
    )
    assert saved["selection"]["source"] == "project"
    assert not context.provider.exists()


def test_missing_explicit_provider_remains_invalid_even_with_project(context):
    context.provider.unlink()
    for project in (None, context.project):
        with pytest.raises(MotionError, match="does not exist"):
            inspect_motion(
                project=project, provider="sample", root=context.root, home=context.home
            )
    with pytest.raises(MotionError, match="does not exist"):
        set_motion_preference(
            scope="provider",
            provider="sample",
            engine="code-drawn",
            root=context.root,
            home=context.home,
        )
    assert not context.provider.exists()


def test_malformed_inferred_provider_does_not_silently_inherit(context):
    context.provider.write_text("{", encoding="utf-8")
    with pytest.raises(MotionError, match="Invalid JSON"):
        inspect_motion(project=context.project, root=context.root, home=context.home)
