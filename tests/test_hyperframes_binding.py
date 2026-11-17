"""Canonical-store and original-closure checks for HyperFrames binding."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from avo.timeline import hyperframes_binding as _MODULE_OBJECT
from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.component_instances import ComponentInstanceService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.proof_validation_stage import proof_validation_batch
from avo.timeline.sync_service import SyncService
from avo.timeline.tracks import TracksService
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_cmap_service import snapshot as cmap_snapshot
from tests.test_timeline_tracks_service import canonical_tracks

resolve_binding = _MODULE_OBJECT.resolve_binding
verify_binding = _MODULE_OBJECT.verify_binding
HyperframesBindingError = _MODULE_OBJECT.HyperframesBindingError


@pytest.mark.parametrize("operation", ["register", "admit"])
def test_generated_service_requires_fresh_hyperframes_observations(
    tmp_path, monkeypatch, operation
):
    from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService

    service = GeneratedAssetService(SimpleNamespace(timeline_dir=tmp_path))
    record = {
        "parameters": {"hyperframes": {"instanceId": "chapter"}},
        "reproducibility": "verified",
    }
    # Other tests exercise schema and media identity; this checks the public gate.
    monkeypatch.setattr(service, "_validate", lambda value: value)
    monkeypatch.setattr(service, "_output", lambda value: None)
    monkeypatch.setattr(service, "load", lambda _: record)
    with pytest.raises(GeneratedAssetError, match="fresh environment"):
        if operation == "register":
            service.register(record)
        else:
            service.admit("chapter")


@pytest.mark.parametrize("fault", [None, "range", "source", "order", "canvas", "fps"])
def test_compiler_binds_canonical_geometry_at_preview_scale(monkeypatch, fault):
    from avo.timeline.proof_plan import ProofPlanCompiler

    binding = {
        "instanceHash": "a" * 64,
        "canonicalInputLock": {
            name: "b" * 64
            for name in ("cmap", "bmap", "tracks", "animation", "sync-map")
        },
        "range": {"startFrame": 9084, "endFrameExclusive": 9264},
        "renderContract": {"frameCount": 180, "frameRate": {"num": 60, "den": 1}},
        "canonicalCanvas": {"width": 2560, "height": 1440},
        "placement": {
            "x": 0,
            "y": 0,
            "width": 2560,
            "height": 1440,
            "zOrder": 100,
            "layerRole": "overlay",
        },
    }
    reference = {"path": "frozen.input-lock.json", "sha256": "c" * 64}
    parameters = {
        "inputLockRef": reference,
        "sourceRange": {"startFrame": 0, "endFrameExclusive": 180},
        "placement": {"x": 0, "y": 0, "width": 640, "height": 360},
        "zOrder": 100,
        "layerRole": "overlay",
    }
    operation = {
        "kind": "overlay-video",
        "outputRange": deepcopy(binding["range"]),
        "parameters": parameters,
    }
    record = {
        "parameters": {
            "hyperframes": {
                "instanceHash": binding["instanceHash"],
                "canonicalInputLock": binding["canonicalInputLock"],
                "inputLockRef": reference,
            }
        }
    }
    output = {"width": 640, "height": 360, "frameRate": {"num": 60, "den": 1}}
    if fault == "range":
        operation["outputRange"]["startFrame"] += 1
    elif fault == "source":
        parameters["sourceRange"]["startFrame"] += 1
    elif fault == "order":
        parameters["zOrder"] += 1
    elif fault == "canvas":
        output["width"] += 1
    elif fault == "fps":
        output["frameRate"]["num"] = 30
    monkeypatch.setattr(_MODULE_OBJECT, "verify_binding", lambda *_: binding)
    compiler = SimpleNamespace(workspace=object())
    if fault:
        with pytest.raises(ValueError, match="canonical|placement|aspect|frame rate"):
            ProofPlanCompiler._require_hyperframes_generated(
                compiler, operation, record, {"binding": binding}, output
            )
    else:
        ProofPlanCompiler._require_hyperframes_generated(
            compiler, operation, record, {"binding": binding}, output
        )


def build(tmp_path, fault=None):
    def snapshot_with_canvas(*args, **kwargs):
        value = cmap_snapshot(*args, **kwargs)
        value["originRef"] = {
            "importId": "a" * 64,
            "exportSha256": "b" * 64,
            "timelinePointer": "/synthetic",
            "proposalSha256": "c" * 64,
            "capabilityVersion": "test",
            "activationId": "d" * 64,
        }
        value["sourceAssemblyPolicy"] = "preserve-import"
        value["importOutput"] = {
            "width": 256,
            "height": 192,
            "frameRate": {"num": 30, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "displayOrigin": None,
        }
        return value

    with patch(
        "tests.test_timeline_approval_service.snapshot",
        side_effect=snapshot_with_canvas,
    ):
        ws, _, _ = approved_workspace(tmp_path)
    project = ws.raw_dir / "edit/derived/hyperframes/chapter/source-r0001"
    project.mkdir(parents=True)
    code = project / "index.html"
    code.write_text("<html><body>Deterministic source</body></html>", encoding="utf-8")
    runtime = project / "lib/gsap.js"
    runtime.parent.mkdir()
    runtime.write_text("/* frozen test vendor; never executed */", encoding="utf-8")
    media = ws.raw_dir / "original.gif"
    media.write_bytes(b"synthetic original GIF bytes; no decode/render claimed")
    font = project / "font.woff2"
    font.write_bytes(b"synthetic original font bytes; never browser-loaded")
    if fault == "proof-original":
        media.write_bytes((ws.raw_dir / "edit/proof.mp4").read_bytes())
    original = {
        "artifactId": "original-gif",
        "fingerprint": file_fingerprint(media),
        "ancestryRole": "original",
    }
    dependency = {
        "artifactId": "font",
        "fingerprint": file_fingerprint(font),
        "ancestryRole": "dependency",
    }
    parameters = {
        "projectRef": {"path": project.relative_to(ws.raw_dir).as_posix()},
        "renderContract": {
            "width": 128,
            "height": 96,
            "frameRate": {"num": 30, "den": 1},
            "frameCount": 9,
        },
        "mediaInputs": [original, dependency],
    }
    if fault == "escape":
        parameters["projectRef"]["path"] = "../outside"
    elif fault == "wrong-count":
        parameters["renderContract"]["frameCount"] = 8
    elif fault == "fractional-frame":
        parameters["renderContract"]["frameRate"] = {"num": 30000, "den": 1001}
    elif fault == "future-output":
        parameters["outputFingerprint"] = file_fingerprint(media)
    elif fault == "media-dependency":
        original["ancestryRole"] = "dependency"
    elif fault == "generated-without-lock":
        original["ancestryRole"] = "generated"
    generated = [{"path": str(code), "sha256": file_fingerprint(code)["sha256"]}]
    generated.append(
        {"path": str(runtime), "sha256": file_fingerprint(runtime)["sha256"]}
    )
    if fault == "outside-code":
        outside = ws.raw_dir / "outside.js"
        outside.write_text("source", encoding="utf-8")
        generated.append(
            {"path": str(outside), "sha256": file_fingerprint(outside)["sha256"]}
        )
    if fault == "untracked":
        (project / "untracked.js").write_text("untracked runtime", encoding="utf-8")
    record = ComponentInstanceService(ws).register(
        {
            "instanceId": "chapter-one",
            "kitId": "test-card",
            "kitVersion": "1.0.0",
            "kitManifestHash": "a" * 64,
            "parameters": parameters,
            "assetBindings": [
                {
                    "slot": item["artifactId"],
                    "sha256": item["fingerprint"]["sha256"],
                    "rightsRef": "test-only-synthetic",
                }
                for item in parameters["mediaInputs"]
            ],
            "eventBindings": [],
            "safeAreaBindings": {"faces": [], "captions": [], "evidence": [], "ui": []},
            "generatedFiles": generated,
            "reviewRefs": [],
        }
    )
    pair = {"instanceId": record["instanceId"], "instanceHash": record["instanceHash"]}
    beat = cue()
    beat.update(kind="card", componentRef="chapter-pair")
    beat["contentRef"]["originalGifAssets"] = [file_fingerprint(media)]
    if fault == "wrong-target":
        beat["targetLayerId"] = "other-layer"
    elif fault == "wrong-component":
        beat["componentRef"] = "other-component"
    BMapService(ws).author({"cues": [beat]}, actor="test", reason="chapter cue")
    tracks = canonical_tracks(ws, ws.raw_dir / "raw.bin")
    layer = {
        "layerId": "graphics",
        "order": 10,
        "zOrder": 10,
        "role": "overlay",
        "generator": {"adapterId": "hyperframes", **pair},
        "animationRef": "chapter-pair",
        "regions": [deepcopy(tracks["videoTracks"]["layers"][0]["regions"][0])],
        "placement": {"x": 0, "y": 0, "width": 256, "height": 192},
    }
    if fault == "wrong-z":
        layer["zOrder"] = 11
    elif fault == "wrong-instance":
        layer["generator"]["instanceHash"] = "b" * 64
    elif fault == "wrong-animation":
        layer["animationRef"] = "other-component"
    elif fault == "invented-range":
        layer["regions"][0]["startTicks"] = 0
    elif fault == "duplicate-region":
        layer["regions"].append(deepcopy(layer["regions"][0]))
    elif fault == "output-source":
        layer["source"] = file_fingerprint(media)
    tracks["videoTracks"]["layers"].append(layer)
    TracksService(ws).author(tracks, actor="test", reason="logical chapter placement")
    value = strategy()
    value["components"][0]["extensions"] = {"hyperframes": pair}
    if fault == "strategy-instance":
        value["components"][0]["extensions"]["hyperframes"] = {
            **pair,
            "instanceHash": "c" * 64,
        }
    AnimationService(ws).author(value, actor="test", reason="chapter lifecycle")
    return SimpleNamespace(
        workspace=ws, project=project, code=code, media=media, instance=record
    )


def test_resolves_real_canonical_heads_without_output_fingerprint(tmp_path):
    asset = build(tmp_path)
    binding = resolve_binding(asset.workspace, "chapter-one")
    assert set(binding["canonicalInputLock"]) == {
        "cmap",
        "bmap",
        "tracks",
        "animation",
        "sync-map",
    }
    assert binding["range"] == {"startFrame": 3, "endFrameExclusive": 12}
    assert binding["placement"] == {
        "x": 0,
        "y": 0,
        "width": 256,
        "height": 192,
        "zOrder": 10,
        "layerRole": "overlay",
    }
    assert binding["canonicalCanvas"] == {"width": 256, "height": 192}
    assert binding["componentContract"]["runtimeDependencies"] == [
        {
            "path": "lib/gsap.js",
            "sha256": file_fingerprint(asset.project / "lib/gsap.js")["sha256"],
        }
    ]
    assert binding["componentContract"]["renderContract"] == binding["renderContract"]
    assert binding["bmapCueId"] == "cue-one"
    assert binding["componentRef"] == "chapter-pair"
    assert binding["project"] == str(asset.project.resolve())
    assert binding["instanceHash"] == asset.instance["instanceHash"]
    assert {item["ancestryRole"] for item in binding["inputs"]} == {
        "source",
        "dependency",
    }
    assert verify_binding(asset.workspace, binding) == binding


@pytest.mark.parametrize(
    "fault",
    [
        "escape",
        "wrong-count",
        "fractional-frame",
        "future-output",
        "media-dependency",
        "generated-without-lock",
        "outside-code",
        "untracked",
        "wrong-target",
        "wrong-component",
        "wrong-z",
        "wrong-instance",
        "wrong-animation",
        "invented-range",
        "duplicate-region",
        "output-source",
        "strategy-instance",
        "proof-original",
    ],
)
def test_rejects_untrusted_or_noncanonical_declarations(tmp_path, fault):
    asset = build(tmp_path, fault)
    with pytest.raises(HyperframesBindingError):
        resolve_binding(asset.workspace, "chapter-one")


@pytest.mark.parametrize(
    "field", ["range", "placement", "canonicalInputLock", "inputs", "instanceHash"]
)
def test_forged_frozen_snapshot_is_not_authority(tmp_path, field):
    asset = build(tmp_path)
    binding = resolve_binding(asset.workspace, "chapter-one")
    binding[field] = "forged"
    with pytest.raises(HyperframesBindingError, match="changed"):
        verify_binding(asset.workspace, binding)


@pytest.mark.parametrize("source", ["code", "media"])
def test_source_mutation_invalidates_frozen_binding(tmp_path, source):
    asset = build(tmp_path)
    binding = resolve_binding(asset.workspace, "chapter-one")
    getattr(asset, source).write_bytes(b"changed original source")
    with pytest.raises(
        HyperframesBindingError, match="fingerprint|changed|reproducible"
    ):
        verify_binding(asset.workspace, binding)


def test_current_head_mutation_invalidates_prior_binding(tmp_path):
    asset = build(tmp_path)
    binding = resolve_binding(asset.workspace, "chapter-one")
    beat = cue()
    beat.update(kind="card", componentRef="chapter-pair")
    BMapService(asset.workspace).author(
        {"cues": [beat]}, actor="test", reason="new head"
    )
    with pytest.raises(HyperframesBindingError):
        verify_binding(asset.workspace, binding)


@pytest.mark.parametrize("native_batch", [False, True])
def test_binding_shares_byte_reads_only_inside_native_proof_batch(
    tmp_path, monkeypatch, native_batch
):
    from avo.timeline.contracts import fingerprint_stage

    asset = build(tmp_path)
    original_open, reads = Path.open, []

    def opened(path, mode="r", *args, **kwargs):
        if path == asset.code and mode == "rb":
            reads.append(path)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    context = proof_validation_batch() if native_batch else fingerprint_stage()
    with context:
        first = resolve_binding(asset.workspace, "chapter-one")
        assert resolve_binding(asset.workspace, "chapter-one") == first
        assert len(reads) == (1 if native_batch else 2)
    assert len(reads) == 2


@pytest.mark.parametrize("change", ["stat", "file-set", "head"])
def test_batch_binding_resolves_source_inventory_and_heads_again(tmp_path, change):
    asset = build(tmp_path)
    original = asset.code.read_bytes()
    with proof_validation_batch():
        binding = resolve_binding(asset.workspace, "chapter-one")
        if change == "stat":
            asset.code.write_bytes(b"changed source with new metadata")
        elif change == "file-set":
            (asset.project / "untracked.html").write_text("new unregistered source")
        else:
            beat = cue()
            beat.update(kind="card", componentRef="chapter-pair")
            BMapService(asset.workspace).author(
                {"cues": [beat]}, actor="test", reason="new head within batch"
            )
        with pytest.raises(HyperframesBindingError):
            verify_binding(asset.workspace, binding)
        if change == "stat":
            asset.code.write_bytes(original)


def test_batch_closing_guard_rehashes_binding_source_despite_same_stat(
    tmp_path, monkeypatch
):
    from avo.timeline import contracts

    asset = build(tmp_path)
    key = contracts._fingerprint_key(asset.code)
    original_key = contracts._fingerprint_key
    monkeypatch.setattr(
        contracts,
        "_fingerprint_key",
        lambda path: key if path == asset.code else original_key(path),
    )
    with pytest.raises(contracts.ContractError, match="changed"):
        with proof_validation_batch():
            resolve_binding(asset.workspace, "chapter-one")
            original = asset.code.read_bytes()
            asset.code.write_bytes(b"X" + original[1:])


def test_unapproved_sync_head_cannot_generate(tmp_path):
    asset = build(tmp_path)
    SyncService(asset.workspace).author_not_applicable(
        raw_fingerprints={"muxed": "b" * 64}, actor="test", reason="new sync head"
    )
    with pytest.raises(HyperframesBindingError):
        resolve_binding(asset.workspace, "chapter-one")


verify_generated_record = _MODULE_OBJECT.verify_generated_record


@pytest.fixture(scope="module")
def receipt_asset(tmp_path_factory):
    from avo.timeline.contracts import content_hash, document_hash_excluding
    from avo.timeline.generated_assets import GeneratedAssetService

    asset = build(tmp_path_factory.mktemp("receipt-canonical"))
    binding = resolve_binding(asset.workspace, "chapter-one")
    tool = asset.workspace.raw_dir / "synthetic-node.exe"
    tool.write_bytes(b"synthetic tool bytes; never executed")
    tool_input = {
        "artifactId": "hyperframes-tool:node",
        "fingerprint": file_fingerprint(tool),
        "ancestryRole": "dependency",
    }
    tool_environment = {
        "files": [file_fingerprint(tool)],
        "version": "0.7.109",
        "versions": {"node": "synthetic"},
    }
    tool_environment["hash"] = content_hash(tool_environment)
    lock = {
        "instanceId": "chapter-one",
        "binding": binding,
        "environment": tool_environment,
    }
    lock["inputLockHash"] = content_hash(lock)
    lock_path = asset.workspace.raw_dir / "edit/derived/receipt.input-lock.json"
    lock_path.write_text(__import__("json").dumps(lock), encoding="utf-8")
    frames = [0, 4, 8]
    hashes = [f"{index:064x}" for index in range(9)]
    capture = {
        "frames": frames,
        "rgbaSha256": {str(index): hashes[index] for index in frames},
    }
    encoded = {
        **binding["renderContract"],
        "silent": True,
        "codec": "ffv1",
        "pixelFormat": "bgra",
        "frameHashes": hashes,
    }
    environment = {
        "toolEnvironment": tool_environment,
        "toolInputs": [tool_input],
        "captureEvidence": capture,
        "encodedVerification": encoded,
    }
    output = asset.workspace.raw_dir / "edit/derived/synthetic.mkv"
    output.write_bytes(b"synthetic receipt output; physical decode not claimed")
    extension = {
        "instanceId": "chapter-one",
        "instanceHash": binding["instanceHash"],
        "inputLockRef": {
            "path": str(lock_path),
            "sha256": file_fingerprint(lock_path)["sha256"],
        },
        "canonicalInputLock": binding["canonicalInputLock"],
        "renderContract": binding["renderContract"],
        "seekEvidence": capture,
        "outputVerification": encoded,
    }
    record = GeneratedAssetService._seal(
        {
            "schemaVersion": "1.0.0",
            "assetId": "chapter-render-one",
            "role": "overlay",
            "generator": {
                "adapterId": "hyperframes",
                "version": "0.7.109",
                "executableSha256": tool_environment["hash"],
            },
            "parameters": {"hyperframes": extension},
            "inputs": [
                *binding["inputs"],
                {
                    "artifactId": "hyperframes-input-lock:chapter-one",
                    "fingerprint": file_fingerprint(lock_path),
                    "ancestryRole": "dependency",
                },
                tool_input,
            ],
            "sourceFree": False,
            "environment": {
                "platform": "synthetic-unit-test",
                "dependencies": {"toolEnvironment": tool_environment["hash"]},
            },
            "output": file_fingerprint(output),
            "reproducibility": "verified",
            "approvalReference": None,
        }
    )
    assert record["recordHash"] == document_hash_excluding(record, "recordHash")
    return asset.workspace, record, environment


def test_verifies_receipt_from_fresh_complete_binding_and_observations(receipt_asset):
    ws, record, environment = receipt_asset
    assert (
        verify_generated_record(ws, deepcopy(record), deepcopy(environment)) == record
    )


@pytest.mark.parametrize(
    "fault",
    [
        "no-observations",
        "missing-input",
        "wrong-instance",
        "wrong-map",
        "wrong-tool",
        "wrong-count",
        "audio",
        "wrong-seek",
        "missing-frame",
        "wrong-lock-ref",
    ],
)
def test_receipt_cannot_claim_missing_or_inconsistent_evidence(receipt_asset, fault):
    from avo.timeline.generated_assets import GeneratedAssetService

    ws, original, observed = receipt_asset
    record, environment = deepcopy(original), deepcopy(observed)
    extension = record["parameters"]["hyperframes"]
    if fault == "no-observations":
        environment = None
    elif fault == "missing-input":
        record["inputs"].pop()
    elif fault == "wrong-instance":
        extension["instanceHash"] = "f" * 64
    elif fault == "wrong-map":
        extension["canonicalInputLock"]["tracks"] = "f" * 64
    elif fault == "wrong-tool":
        environment["toolEnvironment"]["hash"] = "f" * 64
    elif fault == "wrong-count":
        environment["encodedVerification"]["frameCount"] = 8
    elif fault == "audio":
        environment["encodedVerification"]["silent"] = False
    elif fault == "wrong-seek":
        environment["captureEvidence"]["rgbaSha256"]["4"] = "f" * 64
    elif fault == "missing-frame":
        environment["encodedVerification"]["frameHashes"].pop()
    elif fault == "wrong-lock-ref":
        extension["inputLockRef"]["sha256"] = "f" * 64
    record = GeneratedAssetService._seal(record)
    with pytest.raises(HyperframesBindingError):
        verify_generated_record(ws, record, environment)
