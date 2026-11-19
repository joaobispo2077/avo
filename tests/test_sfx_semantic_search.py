"""Optional joint embeddings require pinned local evidence and never fall back."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.adapters.understand.clap_embeddings import LocalClapEncoder
from avo.embedding_manifest import EmbeddingError, load_embedding_manifest
from avo.model_sources import ResolvedJob, disclose_jobs, preflight, resolve_job
from avo.models_cli import build_parser
from avo.models_cli import main as models_main
from avo.sfx_semantic import SemanticSoundRanker, build_semantic_backend
from avo.timeline.contracts import content_hash, validate_document


def manifest_fixture(tmp_path):
    directory = tmp_path / "model"
    directory.mkdir()
    files = {
        "config.json": b'{"model_type":"clap","projection_dim":2}',
        "preprocessor_config.json": b'{"sampling_rate":48000}',
        "pytorch_model.bin": b"fixture weights, never loaded",
        "tokenizer.json": b"{}",
        "LICENSE": b"Apache-2.0 fixture notice",
        "runtime.lock": b"torch==2.6.0\ntransformers==4.57.6\nnumpy==2.2.6\n",
        "decoder.bin": b"decoder fixture",
    }
    for name, data in files.items():
        (directory / name).write_bytes(data)
    doc = {
        "contractVersion": "1.0.0",
        "modelId": "laion/clap-htsat-unfused",
        "revision": "a" * 40,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in files.items()
        },
        "license": {"spdxId": "Apache-2.0", "noticeFile": "LICENSE"},
        "runtime": {
            "pythonVersion": ".".join(map(str, sys.version_info[:3])),
            "pythonSha256": hashlib.sha256(
                Path(sys.executable).read_bytes()
            ).hexdigest(),
            "ffmpegSha256": hashlib.sha256(files["decoder.bin"]).hexdigest(),
            "packages": {"torch": "2.6.0", "transformers": "4.57.6", "numpy": "2.2.6"},
            "lockFile": "runtime.lock",
        },
        "preprocessing": {
            "sampleRate": 48000,
            "channels": 1,
            "maxSeconds": 10,
            "truncation": "rand_trunc",
            "padding": "repeatpad",
            "textMaxLength": 77,
        },
        "dimension": 2,
    }
    path = directory / "manifest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    pin = {
        "id": "clap-htsat-unfused",
        "source": {
            "kind": "artifact",
            "artifactPath": str(directory),
            "manifestPath": str(path),
            "manifestSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "runtime": {
            "pythonEnv": sys.executable,
            "ffmpegPath": str(directory / "decoder.bin"),
            "device": "cpu",
            "offline": True,
            "allowDownload": False,
        },
    }
    return doc, ResolvedJob("audio_embed", pin["id"], pin, {}, "policy")


def test_manifest_requires_actual_model_runtime_and_license_digests(tmp_path):
    doc, job = manifest_fixture(tmp_path)
    verified = load_embedding_manifest(job)
    validate_document(doc, "avo.clap-manifest.schema.json")
    assert verified["jointSpace"]["normalization"] == "l2"
    assert verified["jointSpace"]["dimension"] == 2
    (Path(job.pin["source"]["artifactPath"]) / "pytorch_model.bin").write_bytes(
        b"changed"
    )
    with pytest.raises(EmbeddingError, match="digest"):
        load_embedding_manifest(job)


@pytest.mark.parametrize("field,value", [("offline", False), ("allowDownload", True)])
def test_optional_job_cannot_opt_into_network_execution(tmp_path, field, value):
    _, job = manifest_fixture(tmp_path)
    job.pin["runtime"][field] = value
    with pytest.raises(EmbeddingError, match="offline|download"):
        load_embedding_manifest(job)


def test_named_directory_is_not_embedding_readiness(tmp_path):
    job = ResolvedJob(
        "audio_embed",
        "clap-htsat-unfused",
        {"source": {"artifactPath": str(tmp_path)}, "runtime": {"offline": True}},
        {},
        "p",
    )
    with pytest.raises(Exception, match="manifest|provision"):
        preflight(job)


def test_manifest_escape_unknown_and_unpinned_runtime_rejected(tmp_path):
    doc, job = manifest_fixture(tmp_path)
    path = Path(job.pin["source"]["manifestPath"])
    for change in [
        {"files": {"../escape": "a" * 64}},
        {"command": "download something"},
        {"runtime": {**doc["runtime"], "packages": {"torch": ">=2"}}},
    ]:
        path.write_text(json.dumps({**doc, **change}), encoding="utf-8")
        job.pin["source"]["manifestSha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        with pytest.raises(EmbeddingError):
            load_embedding_manifest(job)


def test_explicit_embedding_jobs_resolve_and_parse_without_becoming_defaults(
    tmp_path, monkeypatch
):
    _, job = manifest_fixture(tmp_path)
    monkeypatch.setattr(
        "avo.models.load_config", lambda *_: {"models": {"audio_embed": job.pin}}
    )
    selected = resolve_job("audio_embed", state={}, provider={}, registry={})
    assert (
        selected.pin["source"]["manifestSha256"] == job.pin["source"]["manifestSha256"]
    )
    assert build_parser().parse_args(["preflight", "audio_embed"]).job == "audio_embed"
    assert set(disclose_jobs(state={})) == {"transcribe", "understand", "plan"}


def test_project_accepts_both_explicit_embedding_jobs():
    validate_document(
        {
            "provider": "bishop",
            "rawDir": "/media/raw",
            "models": {
                "audio_embed": "clap-htsat-unfused",
                "text_embed": "clap-htsat-unfused",
            },
        },
        "avo.project.schema.json",
    )


def test_encoder_constructs_without_loading_or_writing(tmp_path, monkeypatch):
    _, job = manifest_fixture(tmp_path)
    text_job = copy.deepcopy(job)
    text_job.job = "text_embed"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("constructor executed optional runtime")

    monkeypatch.setattr("avo.embedding_runtime.subprocess.run", forbidden)
    LocalClapEncoder(job, text_job)


def test_joint_encoder_rejects_two_different_preprocessing_spaces(tmp_path):
    _, job = manifest_fixture(tmp_path)
    text_job = copy.deepcopy(job)
    text_job.job = "text_embed"
    other = copy.deepcopy(job.pin)
    other["source"]["manifestSha256"] = "0" * 64
    text_job.pin = other
    with pytest.raises(EmbeddingError):
        LocalClapEncoder(job, text_job).preflight()


class Encoder:
    def __init__(self):
        self.calls = []
        self.identity = {
            "dimension": 2,
            "normalization": "l2",
            "modelDigest": "2" * 64,
            "preprocessingDigest": "3" * 64,
            "runtimeDigest": "4" * 64,
        }
        self.identity["id"] = content_hash(self.identity)

    def preflight(self):
        return self.identity

    def encode(self, modality, items):
        self.calls.append((modality, items))
        return {"jointSpace": self.identity, "vectors": [[1.0, 0.0] for _ in items]}


def catalogue(tmp_path):
    source = tmp_path / "sounds"
    source.mkdir()
    data = b"fixture source"
    (source / "hit.wav").write_bytes(data)
    entry = {
        "entryId": "entry",
        "entryRevision": "revision",
        "libraryId": "test",
        "relativePath": "hit.wav",
        "source": {
            "state": "available",
            "sha256": hashlib.sha256(data).hexdigest(),
            "sizeBytes": len(data),
        },
    }
    return source, {"generationId": content_hash({"fixture": 1}), "entries": [entry]}


def test_semantic_unavailable_never_returns_descriptor_results_or_writes(tmp_path):
    source, generation = catalogue(tmp_path)
    workspace = SimpleNamespace(raw_dir=tmp_path / "project")
    ranker = SemanticSoundRanker(workspace, roots={"test": source})
    result = ranker.rank(generation, {"query": "impact", "entryIds": ["entry"]})
    assert result["status"] == "unavailable" and result["scores"] == []
    assert not workspace.raw_dir.exists()


def test_vectors_cache_exact_generation_source_and_space_and_keep_revision(tmp_path):
    source, generation = catalogue(tmp_path)
    encoder = Encoder()
    ranker = SemanticSoundRanker(
        SimpleNamespace(raw_dir=tmp_path / "project"),
        roots={"test": source},
        encoder=encoder,
    )
    request = {"query": "impact", "entryIds": ["entry"]}
    first = ranker.rank(generation, request)
    assert first["status"] == "ready"
    assert first["scores"] == [
        {"entryId": "entry", "entryRevision": "revision", "score": 1.0}
    ]
    ranker.rank(generation, request)
    assert sum(mode == "audio" for mode, _ in encoder.calls) == 1
    generation["generationId"] = content_hash({"fixture": 2})
    ranker.rank(generation, request)
    assert sum(mode == "audio" for mode, _ in encoder.calls) == 2


@pytest.mark.parametrize(
    "vector", [[0.0, 0.0], [float("nan"), 0.0], [True, 0.0], [1.0], [1e100, 0.0]]
)
def test_invalid_or_unnormalized_vectors_are_unavailable(tmp_path, vector):
    source, generation = catalogue(tmp_path)
    encoder = Encoder()
    encoder.encode = lambda modality, items: {
        "jointSpace": encoder.identity,
        "vectors": [vector for _ in items],
    }
    result = SemanticSoundRanker(
        SimpleNamespace(raw_dir=tmp_path / "project"),
        roots={"test": source},
        encoder=encoder,
    ).rank(generation, {"query": "impact", "entryIds": ["entry"]})
    assert result["status"] == "unavailable" and result["scores"] == []


def test_changed_source_or_escaping_path_cannot_use_cached_embedding(tmp_path):
    source, generation = catalogue(tmp_path)
    ranker = SemanticSoundRanker(
        SimpleNamespace(raw_dir=tmp_path / "project"),
        roots={"test": source},
        encoder=Encoder(),
    )
    request = {"query": "impact", "entryIds": ["entry"]}
    assert ranker.rank(generation, request)["status"] == "ready"
    (source / "hit.wav").write_bytes(b"changed")
    assert ranker.rank(generation, request)["status"] == "unavailable"
    generation["entries"][0]["relativePath"] = "../outside.wav"
    assert ranker.rank(generation, request)["status"] == "unavailable"


def test_composition_resolves_both_merged_jobs_without_probing(tmp_path, monkeypatch):
    _, job = manifest_fixture(tmp_path)
    calls = []
    workspace = SimpleNamespace(
        raw_dir=tmp_path / "project",
        project={"provider": "bishop", "models": {"audio_embed": job.pin}},
        video_id="example",
    )

    def resolve(name, **kwargs):
        calls.append((name, kwargs))
        return ResolvedJob(name, job.id, job.pin, {}, "p")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("factory performed a runtime probe")

    monkeypatch.setattr("avo.model_sources.resolve_job", resolve)
    monkeypatch.setattr(LocalClapEncoder, "preflight", forbidden)
    backend = build_semantic_backend(workspace, {}, root=tmp_path)
    assert isinstance(backend, SemanticSoundRanker)
    assert [name for name, _ in calls] == ["audio_embed", "text_embed"]
    assert all(
        kwargs["project"] is workspace.project
        and kwargs["video_key"] == "bishop:example"
        for _, kwargs in calls
    )


def test_encoder_worker_uses_isolated_offline_pinned_process(tmp_path, monkeypatch):
    _, job = manifest_fixture(tmp_path)
    selected_python = tmp_path / "external-python.exe"
    selected_python.write_bytes(Path(sys.executable).read_bytes())
    job.pin["runtime"]["pythonEnv"] = str(selected_python)
    text_job = copy.deepcopy(job)
    text_job.job = "text_embed"
    observed = []

    def run(command, **kwargs):
        payload = json.loads(kwargs["input"])
        observed.append((command, kwargs, payload))
        kwargs["stdout"].write(
            json.dumps(
                {"jointSpace": payload["jointSpace"], "vectors": [[1.0, 0.0]]}
            ).encode()
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("avo.embedding_runtime.subprocess.run", run)
    encoder = LocalClapEncoder(job, text_job)
    identity = encoder.preflight()
    assert encoder.encode("text", ["impact"])["jointSpace"] == identity
    assert all(command[1] == "-I" for command, _, _ in observed)
    assert all(
        command[0] == str(selected_python.resolve()) for command, _, _ in observed
    )
    assert all(
        kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        and kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        for _, kwargs, _ in observed
    )
    assert all(kwargs["timeout"] == 120 for _, kwargs, _ in observed)


def test_manifest_json_budget_is_enforced_before_hashing(tmp_path):
    _, job = manifest_fixture(tmp_path)
    path = Path(job.pin["source"]["manifestPath"])
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(EmbeddingError, match="budget"):
        load_embedding_manifest(job)


def test_decoder_binary_and_preprocessing_implementation_are_bound(tmp_path):
    doc, job = manifest_fixture(tmp_path)
    decoder = Path(job.pin["source"]["artifactPath"]) / "decoder.bin"
    decoder.write_bytes(b"decoder fixture")
    job.pin["runtime"]["ffmpegPath"] = str(decoder)
    doc["runtime"]["ffmpegSha256"] = hashlib.sha256(decoder.read_bytes()).hexdigest()
    doc["files"]["decoder.bin"] = doc["runtime"]["ffmpegSha256"]
    path = Path(job.pin["source"]["manifestPath"])
    path.write_text(json.dumps(doc))
    job.pin["source"]["manifestSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = load_embedding_manifest(job)
    assert result["ffmpeg"] == decoder.resolve()
    decoder.write_bytes(b"changed decoder")
    with pytest.raises(EmbeddingError, match="digest"):
        load_embedding_manifest(job)


def test_backend_rejects_wrong_modality_space_and_cache_tampering(tmp_path):
    source, generation = catalogue(tmp_path)
    encoder = Encoder()
    workspace = SimpleNamespace(raw_dir=tmp_path / "project")
    ranker = SemanticSoundRanker(workspace, roots={"test": source}, encoder=encoder)
    request = {"query": "impact", "entryIds": ["entry"]}
    assert ranker.rank(generation, request)["status"] == "ready"
    cache = next((workspace.raw_dir / "edit/sfx/embeddings").glob("*.json"))
    doc = json.loads(cache.read_text())
    doc["vector"] = [False, 1.0]
    doc["sha256"] = content_hash({"binding": doc["binding"], "vector": doc["vector"]})
    cache.write_text(json.dumps(doc))
    assert ranker.rank(generation, request)["status"] == "ready"
    assert sum(mode == "audio" for mode, _ in encoder.calls) == 2
    encoder.encode = lambda mode, items: {
        "jointSpace": {**encoder.identity, "id": "0" * 64},
        "vectors": [[1.0, 0.0]],
    }
    assert ranker.rank(generation, request)["status"] == "unavailable"


def test_explicit_preflight_discloses_qualified_manifest_without_a_render_claim(
    tmp_path, monkeypatch, capsys
):
    _, job = manifest_fixture(tmp_path)
    monkeypatch.setattr("avo.model_sources.resolve_job", lambda *args, **kwargs: job)
    monkeypatch.setattr("avo.model_sources.preflight", lambda *_: None)
    assert models_main(["preflight", "audio_embed", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["preflight"][0]["modelLoaded"] is False
    assert (
        result["resolvedModelSources"]["audio_embed"]["manifestSha256"]
        == job.pin["source"]["manifestSha256"]
    )


def test_fresh_import_and_composition_never_import_optional_ml_or_start_a_worker(
    tmp_path,
):
    root = Path(__file__).resolve().parents[1]
    program = r"""
import builtins, pathlib, subprocess, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers'}:
        raise AssertionError('optional ML import before explicit rank')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from avo.sfx_semantic import build_semantic_backend
def forbidden(*args, **kwargs):
    raise AssertionError('worker started before explicit rank')
subprocess.run = forbidden
workspace = SimpleNamespace(raw_dir=pathlib.Path(sys.argv[2]), project={}, video_id='fixture')
backend = build_semantic_backend(workspace, {})
assert not workspace.raw_dir.exists()
print('metadata-only composition')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(root / "src"),
            str(tmp_path / "project"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "metadata-only composition" in result.stdout


def test_worker_uses_static_local_only_restricted_weight_loaders():
    from avo.adapters.understand.clap_embeddings_worker import _models

    calls = []

    class Model:
        def to(self, _device):
            return self

        def eval(self):
            return self

    def load(kind, path, **kwargs):
        calls.append((kind, path, kwargs))
        return Model()

    model_type = SimpleNamespace(
        from_pretrained=lambda path, **kwargs: load("model", path, **kwargs)
    )
    processor_type = SimpleNamespace(
        from_pretrained=lambda path, **kwargs: load("processor", path, **kwargs)
    )
    _models(
        {
            "modelPath": "/explicit/local/model",
            "device": "cpu",
            "manifest": {"files": {"pytorch_model.bin": "a" * 64}},
        },
        model_type,
        processor_type,
    )
    assert all(path == "/explicit/local/model" for _, path, _ in calls)
    assert all(
        options["local_files_only"] is True and options["trust_remote_code"] is False
        for _, _, options in calls
    )
    assert calls[0][2]["weights_only"] is True


def test_optional_worker_output_budget_is_enforced(tmp_path, monkeypatch):
    _, job = manifest_fixture(tmp_path)
    text_job = copy.deepcopy(job)
    text_job.job = "text_embed"

    def run(_command, **kwargs):
        kwargs["stdout"].write(b" " * (2 * 1024 * 1024 + 1))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("avo.embedding_runtime.subprocess.run", run)
    with pytest.raises(EmbeddingError, match="byte budget"):
        LocalClapEncoder(job, text_job).preflight()


def test_worker_blocks_all_declared_socket_entrypoints(monkeypatch):
    import socket

    from avo.adapters.understand.clap_embeddings_worker import _disable_network

    hooks = (
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    )
    for owner, name in hooks:
        monkeypatch.setattr(owner, name, getattr(owner, name))
    _disable_network()
    for owner, name in hooks:
        with pytest.raises(RuntimeError, match="forbids network"):
            getattr(owner, name)(None)
