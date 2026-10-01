from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.test_provider_animation_promotion import _propose

from avo.timeline.component_instances import ComponentInstanceService
from avo.timeline.provider_animation import ProviderAnimationService


def test_provider_kit_reuse_creates_fresh_project_owned_instance(tmp_path: Path):
    proposal = _propose(tmp_path, "export const component = ({label}) => label")
    provider = ProviderAnimationService(
        tmp_path / "provider" / "animations" / "animation.json", provider="example"
    )
    event = provider.decide(
        Path(proposal["path"]), decision="approved", actor="creator", reason="approved"
    )
    raw = tmp_path / "second-video"
    workspace = SimpleNamespace(raw_dir=raw, timeline_dir=raw / "edit" / "timeline")
    instance = ComponentInstanceService(workspace).resolve_provider_kit(
        catalog_path=provider.path,
        kit_id="c01-c02",
        version="1.0.0",
        manifest_hash=event["manifestSha256"],
        instance_id="second-video-card",
        parameters={"label": "new video text"},
        asset_bindings=[
            {"slot": "icon", "sha256": "b" * 64, "rightsRef": "new-rights"}
        ],
        event_bindings=[
            {"slot": "entry", "eventId": "event-new", "revisionHash": "c" * 64}
        ],
        safe_area_bindings={
            "faces": ["face-new"],
            "captions": [],
            "evidence": [],
            "ui": [],
        },
        sfx_bindings={"entry": {"sha256": "d" * 64, "rightsRef": "new-sfx-rights"}},
    )
    assert instance["parameters"]["label"] == "new video text"
    assert instance["reviewRefs"] == []
    assert instance["kitManifestHash"] == event["manifestSha256"]
    assert "first-video" not in str(instance)
    assert Path(instance["generatedFiles"][0]["path"]).is_file()
