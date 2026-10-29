"""Shorts engine selection and native producer boundaries; synthetic transport only."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import shorts, shorts_contract, shorts_media, shorts_motion, shorts_plan
from tests.test_shorts_fidelity_integration import _code_drawn_fidelity_context
from tests.test_shorts_plan import (
    FIXTURE_DIR,
    load_motion_request,
    load_request,
    load_transcript,
)


def _binding():
    return {
        "instanceId": "drawing-one",
        "manifestRef": {
            "path": "edit/derived/components/drawing-one/composition.json",
            "sha256": "a" * 64,
        },
        "inputLockRef": {"path": "input-lock.json", "sha256": "b" * 64},
        "generatedAssetRef": {
            "assetId": "drawing-alpha",
            "recordHash": "c" * 64,
            "locator": "receipt.json",
        },
    }


def test_resolved_engine_and_binding_reach_item_status_and_fingerprint(tmp_path):
    request = load_motion_request()
    base = shorts_plan.resolve_batch(
        request,
        load_transcript(),
        request_path=FIXTURE_DIR / "shorts.request.json",
        source_fingerprint="a" * 64,
    )
    request["defaults"].update(motionEngine="code-drawn", codeDrawn=_binding())
    request["candidates"][1]["motionEngine"] = "hyperframes"
    plan = shorts_plan.resolve_batch(
        request,
        load_transcript(),
        request_path=FIXTURE_DIR / "shorts.request.json",
        source_fingerprint="a" * 64,
    )
    assert plan["items"][0]["motionEngine"] == "code-drawn"
    assert plan["items"][0]["codeDrawn"] == _binding()
    assert plan["items"][0]["inputFingerprint"] != base["items"][0]["inputFingerprint"]
    assert plan["items"][1]["motionEngine"] == "hyperframes"
    assert "codeDrawn" not in plan["items"][1]
    status = shorts._new_status(plan, tmp_path / "plan.json")
    shorts_contract.validate_document(status, "status")
    assert status["items"][0]["codeDrawn"] == _binding()
    assert status["items"][1]["motionEngine"] == "hyperframes"


def test_conflicting_or_malformed_motion_binding_never_resolves():
    request = load_motion_request()
    request["candidates"][0].update(motionEngine="hyperframes", codeDrawn=_binding())
    with pytest.raises(shorts_contract.ContractValidationError, match="motionEngine"):
        shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
            source_fingerprint="a" * 64,
        )
    request["candidates"][0]["motionEngine"] = "canvas"
    with pytest.raises(shorts_contract.ContractValidationError):
        shorts_contract.validate_document(request, "request")


def test_native_request_pin_reuses_shared_registry_project_and_invocation_resolution(
    tmp_path, monkeypatch
):
    from avo import video_context
    from avo.motion import resolve_motion_selection

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "avo.project.json").write_text("{}", encoding="utf-8")
    context = SimpleNamespace(raw_dir=raw)
    monkeypatch.setattr(video_context, "resolve_context", lambda **kwargs: context)
    seen = []

    def shared(ctx, **kwargs):
        assert ctx is context
        seen.append(kwargs["invocation"])
        return resolve_motion_selection(
            global_settings={"engine": "hyperframes"},
            provider_settings={"engine": "remotion"},
            project_settings={"engine": "code-drawn"},
            invocation=kwargs["invocation"],
        )

    monkeypatch.setattr(video_context, "resolve_context_motion_selection", shared)
    request = {"defaults": {}}
    shorts._pin_request_motion(request, SimpleNamespace(raw_dir=raw))
    assert request["defaults"]["motionEngine"] == "code-drawn"
    override = {"defaults": {"motionEngine": "hyperframes"}}
    shorts._pin_request_motion(override, SimpleNamespace(raw_dir=raw))
    assert override["defaults"]["motionEngine"] == "hyperframes"
    assert seen == [None, {"engine": "hyperframes"}]
    assert (raw / "avo.project.json").read_text() == "{}"


@pytest.mark.parametrize(
    "unsupported",
    ["remotion", "eight-bit", "graphics", "punchIns", "visualInserts", "split"],
)
def test_unsupported_short_path_fails_before_preparation(
    tmp_path, monkeypatch, unsupported
):
    item = {"motionEngine": "code-drawn", "layout": {"mode": "full-frame"}}
    output = {"pixelFormat": "yuv420p10le"}
    if unsupported == "remotion":
        item["motionEngine"] = unsupported
    elif unsupported == "eight-bit":
        output["pixelFormat"] = "yuv420p"
    elif unsupported == "split":
        item["layout"]["mode"] = "split"
    else:
        item[unsupported] = [{"id": "unsupported-treatment"}]
    with pytest.raises(RuntimeError, match="unsupported|require|port"):
        shorts_motion.require_proof(item, output, None)
    assert list(tmp_path.iterdir()) == []


def test_native_producer_persists_binding_and_uses_no_framework_project(
    tmp_path, monkeypatch
):
    from tests.code_drawn_asset_fixture import synthetic_environment

    workspace, source, _, item, spec, receipt = _code_drawn_fidelity_context(tmp_path)
    item.update(
        id="01",
        expectedOutputBasename="drawing-short",
        captions=[],
        **shorts_motion.pinned_fields(spec),
    )
    item["layout"]["captionAnchor"] = "bottom"
    request = load_request()
    request["source"]["masterPath"] = str(source)
    request_path = workspace.raw_dir / "shorts.request.json"
    shorts_contract.atomic_write_json(request_path, request)
    paths = SimpleNamespace(
        raw_dir=workspace.raw_dir, work_dir=workspace.raw_dir / "edit/shorts/work"
    )
    output = {
        "width": 128,
        "height": 96,
        "fps": 30,
        "frameRateRational": "30/1",
        "pixelFormat": "yuv420p10le",
        "audioChannels": 2,
    }
    plan = {
        "version": "1.2",
        "batchId": "drawing-batch",
        "planHash": "d" * 64,
        "requestPath": str(request_path),
        "output": output,
        "items": [item],
    }
    observed = []

    def forbidden(*args, **kwargs):
        pytest.fail("Native code-drawn producer reached a HyperFrames operation")

    def prepare(original, directory, **kwargs):
        assert original == source
        assert kwargs["source_segments"] == item["sourceSegments"]
        directory.mkdir(parents=True)
        prepared = {}
        for key, silent in (("baseVideo", True), ("dialogueAudio", False)):
            path = directory / (key + ".bin")
            path.write_bytes(key.encode())
            prepared[key] = shorts_media.PreparedAsset(
                path, shorts_media.sha256_file(path), 0.3, silent
            )
        return prepared

    def observe(composition, **kwargs):
        observed.append(composition)
        return synthetic_environment()

    def render(original, destination, **kwargs):
        assert original == source
        assert kwargs["overlay_path"] == Path(receipt["output"]["locator"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"synthetic-unit-proof")
        return {
            "path": str(destination),
            "sha256": shorts_media.sha256_file(destination),
            "canonicalInputLock": kwargs["canonical_lock"],
        }

    monkeypatch.setattr("avo.proof_composition.observe_code_drawn_environment", observe)
    monkeypatch.setattr(shorts, "compile_project", forbidden)
    monkeypatch.setattr(shorts, "build_composition_spec", forbidden)
    monkeypatch.setattr(shorts, "_check_hyperframes_project", forbidden)
    monkeypatch.setattr(shorts.shorts_qc, "generate_contact_sheet", forbidden)
    monkeypatch.setattr(
        shorts_media, "apply_dialogue_gain_if_needed", lambda asset, *a, **k: asset
    )
    monkeypatch.setattr(shorts_media, "ensure_audio_channels", lambda *a, **k: None)
    monkeypatch.setattr(
        "avo.shorts_fidelity_audio.mix_short_audio",
        lambda assets, *a, **k: {
            "path": assets["dialogueAudio"]["path"],
            "sha256": assets["dialogueAudio"]["hash"],
        },
    )
    monkeypatch.setattr(
        "avo.shorts_fidelity.build_microproofs", lambda *a, **k: {"sha256": "e" * 64}
    )
    monkeypatch.setattr("avo.shorts_fidelity.render_fidelity", render)
    row = shorts._build_one_proof(
        plan,
        item,
        workspace.raw_dir / "plan.json",
        {},
        prepare=prepare,
        adapter_factory=forbidden,
        paths=paths,
    )
    assert row["motionEngine"] == "code-drawn"
    assert row["codeDrawn"] == spec["codeDrawn"]
    assert "hyperframesValidation" not in row
    assert row["codeDrawnValidation"]["receiptRecordHash"] == receipt["recordHash"]
    artifact = next(
        value for value in row["artifacts"] if value["kind"] == "composition"
    )
    composition = shorts_contract.load_document(Path(artifact["path"]), "composition")
    assert composition["motionEngine"] == "code-drawn"
    assert composition["codeDrawn"] == spec["codeDrawn"]
    assert len(observed) == 2
    assert not list(paths.work_dir.rglob("hyperframes*"))


def test_code_drawn_hashes_do_not_depend_on_unused_hyperframes_template():
    hashes = shorts._fidelity_implementation_hashes("code-drawn")
    assert "implementation:shorts_motion.py" in hashes
    assert "generator:code-drawn-source" in hashes
    assert not any(
        name in hashes
        for name in (
            "implementation:hyperframes.py",
            "implementation:runtime.js",
            "implementation:index.html",
        )
    )


def test_new_legacy_resolution_pins_global_choice_without_reinterpreting_old_plan(
    tmp_path, monkeypatch
):
    from avo import motion

    request = load_request()
    request_path = tmp_path / "shorts.request.json"
    for name in ("master.mp4", "transcript.json"):
        (tmp_path / name).write_bytes((FIXTURE_DIR / name).read_bytes())
    shorts_contract.atomic_write_json(request_path, request)
    before = request_path.read_bytes()
    monkeypatch.setattr(
        motion,
        "inspect_motion",
        lambda **kwargs: {
            "selection": motion.resolve_motion_selection(
                global_settings={"engine": "remotion"}, invocation=kwargs["invocation"]
            )
        },
    )
    plan_path = tmp_path / "plans/shorts.plan-v001.json"
    assert (
        shorts.main(["resolve", str(request_path), "--output", str(plan_path)])
        == shorts.EXIT_OK
    )
    plan = shorts_contract.load_document(plan_path, "plan")
    assert all(item["motionEngine"] == "remotion" for item in plan["items"])
    assert request_path.read_bytes() == before
    old = {"layout": {"mode": "full-frame"}}
    assert shorts_motion.engine(old) == "hyperframes"


def test_masked_contrary_motion_binding_is_invalid_at_public_request_boundary():
    request = load_motion_request()
    request["defaults"].update(motionEngine="hyperframes", codeDrawn=_binding())
    for candidate in request["candidates"]:
        candidate["motionEngine"] = "code-drawn"
    with pytest.raises(shorts_contract.ContractValidationError):
        shorts_contract.validate_document(request, "request")
    with pytest.raises(shorts_contract.ContractValidationError):
        shorts_plan.resolve_batch(
            request,
            load_transcript(),
            request_path=FIXTURE_DIR / "shorts.request.json",
            source_fingerprint="a" * 64,
        )


@pytest.mark.parametrize("canonical_paths", [False, True])
def test_effective_contrary_engine_rejects_before_registry_or_snapshot_write(
    tmp_path, monkeypatch, canonical_paths
):
    from avo import motion

    request = load_request()
    request["defaults"]["codeDrawn"] = _binding()
    path = tmp_path / "shorts.request.json"
    shorts_contract.atomic_write_json(path, request)
    original = path.read_bytes()
    monkeypatch.setattr(
        motion,
        "inspect_motion",
        lambda **kwargs: {
            "selection": motion.resolve_motion_selection(
                global_settings={"engine": "hyperframes"},
                invocation=kwargs["invocation"],
            )
        },
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid effective request reached registry writes")

    monkeypatch.setattr(shorts.shorts_paths, "register_batch", forbidden)
    arguments = [
        "resolve",
        str(path),
        "--output",
        str(tmp_path / "plans/shorts.plan-v001.json"),
    ]
    if canonical_paths:
        raw = tmp_path / "raw"
        raw.mkdir()
        arguments.extend(["--raw-dir", str(raw)])
    assert shorts.main(arguments) == shorts.EXIT_INVALID
    assert not list(tmp_path.rglob("shorts.plan*.json"))
    assert not list(tmp_path.rglob("shorts.request-v*.json"))
    assert path.read_bytes() == original
