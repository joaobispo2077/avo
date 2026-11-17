"""Size filtering may avoid negative bytes but never weaken output quarantine."""

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.timeline import contracts, hyperframes_binding, migration
from avo.timeline.component_instances import ComponentInstanceService
from avo.timeline.generated_assets import GeneratedAssetService
from avo.timeline.media_admission import (
    MediaAdmissionError,
    require_media_admission,
    require_no_forbidden_outputs,
)
from tests.test_generated_assets import _record as generated_record
from tests.test_historical_output_records import _record as historical_record
from tests.test_historical_output_records import _write as write_historical_record
from tests.test_hyperframes_binding import build


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def observe_reads(monkeypatch, paths):
    watched = {path.resolve() for path in paths}
    original = Path.open
    reads = []

    def opened(path, mode="r", *args, **kwargs):
        if mode == "rb" and path.resolve() in watched:
            reads.append(path.resolve())
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    return reads


def workspace(raw):
    return SimpleNamespace(raw_dir=raw, timeline_dir=raw / "edit/timeline")


def test_lazy_inventory_does_not_consume_one_shot_recursive_inputs(tmp_path):
    source = write(tmp_path / "source.gif", b"copied-preview")
    write(tmp_path / "edit/preview/old.mp4", source.read_bytes())
    output = write(tmp_path / "generated.png", b"new-title-card")
    fingerprint = contracts.file_fingerprint(source)
    reference = {"artifactId": "raw-source", "fingerprint": fingerprint}
    asset = generated_record(output)
    asset["inputs"] = iter([reference])
    contributor = {
        "assetId": asset["assetId"],
        "kind": "generated",
        "fingerprint": asset["output"],
    }

    with pytest.raises(MediaAdmissionError, match="PROOF_FORBIDDEN_ANCESTOR"):
        require_media_admission(
            [contributor],
            registered_originals=[
                {"sourceId": "raw-source", "fingerprint": fingerprint}
            ],
            generated_assets={asset["assetId"]: asset},
            known_outputs=GeneratedAssetService(workspace(tmp_path))._known_outputs(),
        )


def test_inventory_does_not_open_different_sized_negative_media(tmp_path, monkeypatch):
    matching = write(tmp_path / "edit/preview/matching.mp4", b"small")
    unrelated = write(tmp_path / "edit/preview/unrelated.mp4", b"x" * 4096)
    reads = observe_reads(monkeypatch, [matching, unrelated])
    known = migration.inventory_historical_output_fingerprints(
        tmp_path, candidate_sizes=frozenset({5})
    )
    assert {item["sha256"] for item in known} == {hashlib.sha256(b"small").hexdigest()}
    assert reads == [matching.resolve()]


@pytest.mark.parametrize("wrapper", ["direct", "fingerprint", "output"])
def test_service_checks_all_supported_candidate_fingerprint_shapes(
    tmp_path, monkeypatch, wrapper
):
    source = write(tmp_path / "source.gif", b"small")
    matching = write(tmp_path / "edit/preview/copy.mp4", b"small")
    unrelated = write(tmp_path / "edit/preview/large.mp4", b"x" * 4096)
    fingerprint = contracts.file_fingerprint(source)
    candidate = fingerprint if wrapper == "direct" else {wrapper: fingerprint}
    reads = observe_reads(monkeypatch, [matching, unrelated])
    known = GeneratedAssetService(workspace(tmp_path))._inventory_outputs(
        candidates=[candidate]
    )
    assert {item["sha256"] for item in known} == {fingerprint["sha256"]}
    assert reads == [matching.resolve()]


def test_service_reenumerates_new_matching_outputs_on_every_call(tmp_path):
    source = write(tmp_path / "source.gif", b"original")
    candidate = contracts.file_fingerprint(source)
    service = GeneratedAssetService(workspace(tmp_path))
    with contracts.fingerprint_stage():
        assert service._inventory_outputs(candidates=[candidate]) == []
        preview = write(tmp_path / "edit/preview/new.mp4", b"original")
        known = service._inventory_outputs(candidates=[candidate])
        assert {item["sha256"] for item in known} == {candidate["sha256"]}
        assert known[0]["locator"] == str(preview)


def test_matching_negative_bytes_are_fresh_despite_outer_cached_stat_identity(
    tmp_path, monkeypatch
):
    source = write(tmp_path / "source.gif", b"original")
    preview = write(tmp_path / "edit/preview/old.mp4", b"original")
    candidate = contracts.file_fingerprint(source)
    key = contracts._fingerprint_key(preview)
    original_key = contracts._fingerprint_key
    monkeypatch.setattr(
        contracts,
        "_fingerprint_key",
        lambda path: key if path == preview else original_key(path),
    )
    service = GeneratedAssetService(workspace(tmp_path))
    with contracts.fingerprint_stage():
        cached = contracts.file_fingerprint(preview)
        reads = observe_reads(monkeypatch, [preview])
        assert (
            service._inventory_outputs(candidates=[candidate])[0]["sha256"]
            == cached["sha256"]
        )
        stat = preview.stat()
        preview.write_bytes(b"replaced")
        os.utime(preview, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert contracts.file_fingerprint(preview) == cached
        current = service._inventory_outputs(candidates=[candidate])
        assert current[0]["sha256"] == hashlib.sha256(b"replaced").hexdigest()
        assert reads == [preview.resolve(), preview.resolve()]


@pytest.mark.parametrize("operation", ["rename", "delete"])
@pytest.mark.parametrize("custom_root", [False, True])
def test_recorded_outputs_stay_forbidden_when_filter_excludes_size_and_file_is_gone(
    tmp_path, operation, custom_root
):
    original = write(tmp_path / "edit/preview/old.mkv", b"previously rendered output")
    expected = contracts.file_fingerprint(original)
    timeline = (
        tmp_path / "custom-timeline" if custom_root else tmp_path / "edit/timeline"
    )
    write_historical_record(
        tmp_path,
        historical_record(tmp_path, "proof-plan", output=expected),
        timeline_dir=timeline,
    )
    relocated = tmp_path / "renamed-original.gif"
    if operation == "rename":
        original.rename(relocated)
    else:
        relocated.write_bytes(original.read_bytes())
        original.unlink()
    known = migration.inventory_historical_output_fingerprints(
        tmp_path, timeline_dir=timeline, candidate_sizes=frozenset({0})
    )
    assert {item["sha256"] for item in known} == {expected["sha256"]}
    with pytest.raises(MediaAdmissionError, match="PROOF_FORBIDDEN_ANCESTOR"):
        require_no_forbidden_outputs(
            [{**contracts.file_fingerprint(relocated), "mediaClass": "source"}],
            known_outputs=known,
        )


@pytest.mark.parametrize(
    "problem",
    [
        "missing-size",
        "none",
        "bool",
        "negative",
        "float",
        "text",
        "mismatch",
        "missing-locator",
        "absent-file",
        "invalid-entry",
    ],
)
def test_any_unknown_or_untrusted_candidate_forces_full_scan(
    tmp_path, monkeypatch, problem
):
    source = write(tmp_path / "source.gif", b"x")
    matching = write(tmp_path / "edit/preview/small.mp4", b"x")
    unrelated = write(tmp_path / "edit/preview/large.mp4", b"x" * 4096)
    good = contracts.file_fingerprint(source)
    invalid = deepcopy(good)
    if problem == "missing-size":
        invalid.pop("sizeBytes")
    elif problem == "missing-locator":
        invalid.pop("locator")
    elif problem == "absent-file":
        invalid["locator"] = str(tmp_path / "missing.gif")
    elif problem == "invalid-entry":
        invalid = None
    else:
        invalid["sizeBytes"] = {
            "none": None,
            "bool": True,
            "negative": -1,
            "float": 1.0,
            "text": "1",
            "mismatch": 2,
        }[problem]
    reads = observe_reads(monkeypatch, [matching, unrelated])
    known = GeneratedAssetService(workspace(tmp_path))._inventory_outputs(
        candidates=[{"fingerprint": good}, invalid]
    )
    assert {item["locator"] for item in known} == {str(matching), str(unrelated)}
    assert set(reads) == {matching.resolve(), unrelated.resolve()}


def test_default_service_call_still_scans_without_candidate_authority(tmp_path):
    preview = write(tmp_path / "edit/preview/old.mp4", b"ordinary historical output")
    known = GeneratedAssetService(workspace(tmp_path))._inventory_outputs()
    assert {item["sha256"] for item in known} == {
        contracts.file_fingerprint(preview)["sha256"]
    }


def test_lazy_provider_uses_direct_quarantine_contributors_without_eager_hashing(
    tmp_path, monkeypatch
):
    source = write(tmp_path / "source.gif", b"original")
    matching = write(tmp_path / "edit/preview/copy.mp4", b"original")
    unrelated = write(tmp_path / "edit/preview/large.mp4", b"x" * 4096)
    candidate = contracts.file_fingerprint(source)
    reads = observe_reads(monkeypatch, [matching, unrelated])
    provider = GeneratedAssetService(workspace(tmp_path))._known_outputs()
    assert reads == []
    with pytest.raises(MediaAdmissionError, match="PROOF_FORBIDDEN_ANCESTOR"):
        require_no_forbidden_outputs([candidate], known_outputs=provider)
    assert reads == [matching.resolve()]


def test_zero_byte_candidate_is_valid_but_does_not_hash_nonzero_outputs(
    tmp_path, monkeypatch
):
    source = write(tmp_path / "source.gif", b"")
    matching = write(tmp_path / "edit/preview/empty.mp4", b"")
    unrelated = write(tmp_path / "edit/preview/nonempty.mp4", b"not empty")
    reads = observe_reads(monkeypatch, [matching, unrelated])
    known = GeneratedAssetService(workspace(tmp_path))._inventory_outputs(
        candidates=[contracts.file_fingerprint(source)]
    )
    assert {item["sha256"] for item in known} == {hashlib.sha256(b"").hexdigest()}
    assert reads == [matching.resolve()]


def test_hyperframes_recursive_generated_reference_cannot_hide_preview_bytes(
    tmp_path, monkeypatch
):
    asset = build(tmp_path)
    ws = asset.workspace
    binding = hyperframes_binding.resolve_binding(ws, "chapter-one")
    lock = {"canonicalInputLock": binding["canonicalInputLock"]}
    lock["inputLockHash"] = contracts.content_hash(lock)
    lock_path = ws.raw_dir / "edit/derived/recursive.input-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    lock_ref = {
        "path": str(lock_path),
        "sha256": contracts.file_fingerprint(lock_path)["sha256"],
    }
    forbidden = b"previous proof picture bytes".ljust(127, b"!")
    preview = write(ws.raw_dir / "edit/preview/prior.mp4", forbidden)
    unrelated = write(ws.raw_dir / "edit/preview/unrelated.mp4", b"x" * 65537)
    dependency = write(ws.raw_dir / "renamed-font.woff2", forbidden)
    service = GeneratedAssetService(ws)
    reference = {
        "artifactId": "renamed-dependency",
        "ancestryRole": "dependency",
        "fingerprint": contracts.file_fingerprint(dependency),
    }
    for identity in ("generated-leaf", "generated-parent"):
        output = write(ws.raw_dir / f"edit/derived/{identity}.png", identity.encode())
        record = generated_record(output)
        record.update(
            assetId=identity,
            sourceFree=False,
            inputs=[reference],
            parameters={"inputLockRef": lock_ref},
        )
        service.register(record)
        reference = {
            "artifactId": identity,
            "ancestryRole": "generated",
            "fingerprint": contracts.file_fingerprint(output),
        }
    reads = observe_reads(monkeypatch, [preview, unrelated])
    with pytest.raises(MediaAdmissionError, match="PROOF_FORBIDDEN_ANCESTOR"):
        hyperframes_binding._admit_binding_inputs(
            ws,
            ws.raw_dir,
            "chapter-one",
            ComponentInstanceService(ws),
            [reference],
            [],
            binding["canonicalInputLock"],
        )
    assert preview.resolve() in reads
    assert unrelated.resolve() not in reads
