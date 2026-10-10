from pathlib import Path

import pytest

from avo.init_project import build_project
from avo.video_context import VideoContext, merge_config, resolve_context_cutting_policy

pytestmark = pytest.mark.integration


def test_registry_does_not_override_cutting_and_config_resolution_is_read_only(
    monkeypatch,
):
    from avo import video_context

    global_settings = {
        "enabled": True,
        "family": "analysis-review",
        "intensity": "conservative",
        "guards": {"beforeMs": 200, "afterMs": 200},
    }
    monkeypatch.setattr(
        video_context, "load_config", lambda root: {"cutting": global_settings}
    )
    monkeypatch.setattr(
        video_context,
        "_provider_manifest",
        lambda ctx, root: {"routingOverrides": {"cutting": {"intensity": "balanced"}}},
    )
    context = VideoContext(
        provider="test",
        video_id=None,
        raw_dir=Path("."),
        video_key=None,
        registry={"defaults": {"cutting": {"intensity": "conservative"}}},
        project={"cutting": {"guards": {"beforeMs": 250}}},
    )
    policy = resolve_context_cutting_policy(
        context, invocation={"intensity": "dynamic"}
    )
    assert policy.effective["intensity"] == "dynamic"
    assert policy.effective["guards"] == {"beforeMs": 250, "afterMs": 200}
    assert context.project == {"cutting": {"guards": {"beforeMs": 250}}}
    merged = merge_config(context)
    assert merged["cutting"]["guards"] == {"beforeMs": 250, "afterMs": 200}
    assert merged["cutting"]["intensity"] == "balanced"


def test_initialization_only_copies_explicit_cutting_request():
    project = build_project("test", "footage", config={"cutting": {"enabled": True}})
    assert "cutting" not in project
    project = build_project("test", "footage", cutting_settings={"enabled": False})
    assert project["cutting"] == {"enabled": False}


def test_actual_workspace_factory_exposes_disabled_policy_without_provisioning(
    tmp_path,
):
    from avo.adapters.registry import build_cutting_service
    from cutting_fixtures import cutting_workspace

    workspace, _ = cutting_workspace(tmp_path)
    assert build_cutting_service(workspace).status()["status"] == "disabled"
