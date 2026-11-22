from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
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


@pytest.mark.integration
@pytest.mark.native_artcraft
def test_native_provider_variants_stay_owned_by_three_projects(tmp_path):
    from tests.integration.test_artcraft_lower_third_runtime import (
        _job_contract,
        _publish_fixture_package,
    )
    from tests.test_artcraft_component_reuse import _resolve

    from avo.adapters.artcraft_anicraft import (
        inspect_lower_third_source,
        revise_lower_third,
        run_lower_third,
    )
    from avo.timeline.contracts import file_fingerprint
    from avo.timeline.workspace import TimelineWorkspace

    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip("Select the installed AniCraft 0.2.1 CLI")
    executable = Path(entry).resolve(strict=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("ANICRAFT_")
    }

    def invoke(directory, *arguments, timeout):
        return subprocess.run(
            [str(executable), *map(str, arguments)],
            cwd=directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    budget = {"seconds": 60, "files": 128, "bytes": 16_000_000}
    defaults = {"primaryText": "Host", "font": "Arial"}
    versions = {}
    for version, (width, height) in (("1.0.0", (640, 360)), ("2.0.0", (360, 640))):
        output = {**_job_contract(), "width": width, "height": height}
        result = run_lower_third(
            output,
            defaults,
            directory=tmp_path / ("source-" + version),
            budget=budget,
            invoke=invoke,
        )
        native = Path(result["nativeSource"]["locator"])
        provider, store, event = _publish_fixture_package(
            tmp_path,
            native,
            output,
            inspect_lower_third_source,
            version=version,
            parameters=defaults,
        )
        versions[version] = (output, (provider, store, event["manifestSha256"], native))

    project_services = {}
    for name in ("video-one", "video-two", "video-three"):
        raw = tmp_path / name
        raw.mkdir()
        project = raw / "avo.project.json"
        project.write_text(
            json.dumps(
                {"videoId": name, "provider": "first-channel", "rawDir": str(raw)}
            ),
            encoding="utf-8",
        )
        project_services[name] = ComponentInstanceService(
            TimelineWorkspace.from_project(project)
        )

    fingerprints, pins = {}, []
    variants = (
        ("video-one", "1.0.0", "Clara", None),
        ("video-two", "1.0.0", "Diego", None),
        ("video-three", "2.0.0", "Mar\u00eda", None),
        ("video-one", "2.0.0", "Rafa", "clara"),
        ("video-two", "1.0.0", "Sofia", None),
    )
    holds = set()
    for name, version, text, supersedes in variants:
        service = project_services[name]
        output, library = versions[version]
        instance_id = text.lower().replace("\u00ed", "i")
        options = {
            "text": text,
            "instance_id": instance_id,
            "version": version,
            "source_observer": inspect_lower_third_source,
            "supersedes_instance_id": supersedes,
        }
        pin = _resolve(service, library, **options)
        assert pin["kitVersion"] == version and pin["reviewRefs"] == []
        assert pin.get("supersedesInstanceId") == supersedes
        owned = next(
            Path(item["path"])
            for item in pin["generatedFiles"]
            if item["path"].endswith(".anicraft")
        )
        assert owned.is_relative_to(service.workspace.raw_dir)
        assert owned.read_bytes() == library[3].read_bytes()
        fingerprints[owned] = file_fingerprint(owned)
        result = revise_lower_third(
            output,
            defaults,
            pin["parameters"],
            source=owned,
            directory=service.workspace.raw_dir / ("derived-" + instance_id),
            budget=budget,
            invoke=invoke,
        )
        assert result["sourceObservations"]["editableText"] == text
        with Image.open(result["frames"][8]["locator"]) as hold:
            assert hold.size == (output["width"], output["height"])
        holds.add(result["frames"][8]["sha256"])
        pins.append((service, library, options, pin))

    assert len(holds) == len(fingerprints) == 5
    assert {path: file_fingerprint(path) for path in fingerprints} == fingerprints
    for service, library, options, pin in pins:
        assert (
            service.load(pin["instanceId"])
            == _resolve(service, library, **options)
            == pin
        )
