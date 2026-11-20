"""Concrete proof dependencies for entry points and legacy default bridges.

Timeline application services receive these dependencies explicitly from CLI.
Legacy calls may resolve the same defaults here without constructing adapters
inside the timeline. Imports stay lazy to preserve optional tool loading.
"""

import json
from copy import deepcopy
from pathlib import Path


def create_timeline_render_port():
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    return TimelineRenderAdapter()


def create_sync_materializer():
    from avo.adapters.media.sync_materializer import SyncMaterializer

    return SyncMaterializer()


def probe_audio_sample_rate(selection: dict, locator: Path) -> int:
    from avo.adapters.media.ffprobe import audio_sample_rate

    return audio_sample_rate(selection, locator)


def create_motion_materializer():
    """Supply the optional renderer only for an explicit canonical generation."""

    def materializer(workspace, instance_id, *, output):
        strategy_store = workspace.store("animation")
        strategy_index = workspace.require_active("animation")
        strategy = strategy_store.revision(strategy_index["headRevisionId"])["snapshot"]
        if strategy.get("framework", "hyperframes") == "hyperframes":
            from avo.adapters.motion.hyperframes import HyperframesAdapter
            from avo.adapters.motion.hyperframes_materialize import materialize

            return materialize(
                HyperframesAdapter(), workspace, instance_id, output=output
            )
        from avo.adapters.motion.code_drawn import CodeDrawnAdapter
        from avo.motion import materialize_code_drawn

        return materialize_code_drawn(
            workspace, instance_id, output=output, adapter=CodeDrawnAdapter()
        )

    return materializer


def create_generated_asset_validator(workspace):
    """Observe optional runtimes outside timeline services before admitting media."""

    def validator(reference, input_lock_ref, canonical_lock):
        from avo.timeline.generated_assets import GeneratedAssetService

        service = GeneratedAssetService(workspace)
        record = service.load(reference["assetId"])
        if record["recordHash"] != reference["recordHash"]:
            raise ValueError("generated asset record identity changed")
        if record.get("parameters", {}).get("artcraft"):
            return _admit_artcraft(
                workspace, service, record, input_lock_ref, canonical_lock
            )
        hyperframes = record.get("parameters", {}).get("hyperframes")
        if hyperframes:
            return _admit_hyperframes(
                workspace, service, record, input_lock_ref, canonical_lock
            )
        extension = record.get("parameters", {}).get("codeDrawn")
        environment = None
        if extension:
            if extension["inputLockRef"] != input_lock_ref:
                raise ValueError("generated input-lock reference differs")
            if any(
                canonical_lock.get(key) != value
                for key, value in extension.get("canonicalInputLock", {}).items()
            ):
                raise ValueError(
                    "generated canonical input lock differs from the frozen plan"
                )
            composition = Path(extension["manifestRef"]["path"])
            if not composition.is_absolute():
                composition = workspace.raw_dir / composition
            lock = json.loads(Path(input_lock_ref["path"]).read_text(encoding="utf-8"))
            service.validate_code_drawn_inputs(lock["inputs"])
            environment = observe_code_drawn_environment(
                composition, expected_evidence=extension["captureEvidence"]
            )
        return service.admit(reference["assetId"], code_drawn_environment=environment)

    return validator


def register_artcraft_export(workspace, *, job_ref, expected_head, output, asset_id):
    """Register one explicitly selected native export after observing source and alpha."""
    from avo.adapters.media.artcraft_alpha import pack_alpha_sequence
    from avo.timeline.artcraft_binding import (
        build_artcraft_asset_record,
        freeze_export_binding,
    )
    from avo.timeline.contracts import file_fingerprint
    from avo.timeline.generated_assets import GeneratedAssetService
    from avo.timeline.store import write_immutable_json

    service = GeneratedAssetService(workspace)
    service.path(asset_id)
    binding = freeze_export_binding(
        workspace, job_ref=job_ref, expected_head=expected_head
    )
    _observe_artcraft_source(binding)
    output_root = workspace.raw_dir.resolve() / "edit" / "derived"
    output = Path(output)
    lock_path = output.with_suffix(".source.json")
    if lock_path.resolve() != lock_path or (
        lock_path.exists() and lock_path.stat().st_nlink != 1
    ):
        raise ValueError("ArtCraft source lock needs an owned derived path")
    observed = pack_alpha_sequence(
        binding["frames"], binding["outputContract"], output, output_root=output_root
    )
    write_immutable_json(lock_path, binding)
    record = build_artcraft_asset_record(
        binding, file_fingerprint(lock_path), observed, asset_id=asset_id
    )
    return service.register(record, artcraft_observations=observed)


def _observe_artcraft_source(binding):
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source

    if binding["environment"]["app"] != "anicraft":
        raise ValueError(
            "No verified ArtCraft source profile is available for this app"
        )
    source = binding["nativeSource"]
    observed = inspect_lower_third_source(
        Path(source["locator"]),
        binding["outputContract"],
        binding["parameters"],
        max_bytes=binding["nativeByteBudget"],
    )
    if observed["fingerprint"] != source:
        raise ValueError("ArtCraft native source changed during observation")


def _admit_artcraft(workspace, service, record, input_lock_ref, canonical_lock):
    from avo.adapters.media.artcraft_alpha import observe_alpha_sequence
    from avo.timeline.artcraft_binding import read_artcraft_binding

    receipt = record["parameters"]["artcraft"]
    ref = receipt["bindingRef"]
    if input_lock_ref != {"path": ref["locator"], "sha256": ref["sha256"]}:
        raise ValueError(
            "ArtCraft input-lock reference differs from its frozen receipt"
        )
    binding = read_artcraft_binding(workspace, ref)
    required = ("cmap", "bmap", "tracks", "animation", "sync-map")
    heads = binding["canonical"]["heads"]
    if any(
        key not in heads or canonical_lock.get(key) != heads[key] for key in required
    ):
        raise ValueError("ArtCraft canonical inputs differ from the frozen proof plan")
    _observe_artcraft_source(binding)
    observed = observe_alpha_sequence(
        binding["frames"],
        binding["outputContract"],
        Path(record["output"]["locator"]),
        output_root=workspace.raw_dir.resolve() / "edit" / "derived",
    )
    admitted = service.admit(record["assetId"], artcraft_observations=observed)
    if admitted != record:
        raise ValueError("ArtCraft generated asset changed during admission")
    return admitted


def _guard_hyperframes_dependencies(service, record):
    from avo.timeline.contracts import file_fingerprint

    # Binding resolution has its own byte stage; enroll originals in this batch too.
    for item in [*record["inputs"], {"fingerprint": record["output"]}]:
        expected = item["fingerprint"]
        actual = file_fingerprint(Path(expected["locator"]))
        if any(actual[key] != expected[key] for key in ("sha256", "sizeBytes")):
            raise ValueError("HyperFrames dependency fingerprint changed")
    file_fingerprint(service.path(record["assetId"]))


def _admit_hyperframes(workspace, service, record, input_lock_ref, canonical_lock):
    from avo.adapters.motion.hyperframes import HyperframesAdapter
    from avo.adapters.motion.hyperframes_materialize import observe
    from avo.timeline.contracts import content_hash
    from avo.timeline.hyperframes_binding import resolve_binding
    from avo.timeline.proof_validation_stage import proof_pixel_observations

    extension = record["parameters"]["hyperframes"]
    if extension["inputLockRef"] != input_lock_ref:
        raise ValueError("HyperFrames input-lock reference differs")
    binding = resolve_binding(workspace, extension["instanceId"])
    if any(
        canonical_lock.get(key) != value
        for key, value in binding["canonicalInputLock"].items()
    ):
        raise ValueError("HyperFrames canonical input lock differs")
    output = Path(record["output"]["locator"]).resolve()
    if not output.is_relative_to(workspace.raw_dir.resolve() / "edit/derived"):
        raise ValueError("HyperFrames generated output escaped edit/derived")
    observations, environment = proof_pixel_observations(), None
    if observations is not None:
        key = (
            "hyperframes-admission-environment",
            content_hash(
                {
                    "binding": binding,
                    "recordHash": record["recordHash"],
                    "inputLockRef": input_lock_ref,
                    "canonicalInputLock": canonical_lock,
                    "output": record["output"],
                }
            ),
        )
        environment = deepcopy(observations.get(key))
    if environment is None:
        environment = observe(HyperframesAdapter(), workspace, binding, output=output)
    admitted = service.admit(record["assetId"], hyperframes_environment=environment)
    if admitted["recordHash"] != record["recordHash"]:
        raise ValueError("generated asset record identity changed during admission")
    if observations is not None:
        _guard_hyperframes_dependencies(service, record)
        observations[key] = deepcopy(environment)
    return admitted


def observe_code_drawn_environment(
    composition: Path, *, expected_evidence: dict | None = None
) -> dict[str, object]:
    """Observe the actual runtime and compare fresh pixels before receipt reuse."""
    from avo.adapters.motion.code_drawn import CodeDrawnAdapter
    from avo.motion import MotionError

    evidence = CodeDrawnAdapter().check(composition)["checks"][0]["evidence"]
    if expected_evidence is not None and any(
        evidence.get(key) != expected_evidence.get(key)
        for key in ("frames", "rgbaSha256")
    ):
        raise MotionError(
            "CODE_DRAWN_LOCK_STALE",
            "Current captured RGBA pixels differ from the generated receipt.",
        )
    return evidence["environment"]
