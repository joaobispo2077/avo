"""Optional offline worker. Never imported by default AVO reads or searches."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def _deny_network(*_args, **_kwargs):
    raise RuntimeError("embedding worker forbids network/downloads")


def _disable_network():
    for owner, name in (
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ):
        setattr(owner, name, _deny_network)


def _runtime(request):
    _disable_network()
    runtime = request["manifest"]["runtime"]
    if ".".join(map(str, sys.version_info[:3])) != runtime["pythonVersion"]:
        raise RuntimeError("embedding Python version mismatch")
    for package, expected in runtime["packages"].items():
        if importlib.metadata.version(package) != expected:
            raise RuntimeError(f"embedding runtime version mismatch: {package}")
    import numpy as np
    import torch
    from transformers import ClapModel, ClapProcessor

    if tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2]) < (2, 6):
        raise RuntimeError("restricted CLAP weights require Torch 2.6 or newer")
    if request["device"] not in {"cpu", "cuda"}:
        raise RuntimeError("embedding device must be cpu or cuda")
    if request["device"] == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("selected embedding CUDA runtime is unavailable")
    torch.set_num_threads(1)
    torch.manual_seed(0)
    np.random.seed(0)
    return np, torch, ClapModel, ClapProcessor


def _audio(item, request, np):
    source = Path(item["path"])
    if not source.is_file() or source.stat().st_size > 512 * 1024 * 1024:
        raise RuntimeError("embedding source missing or exceeds its byte budget")
    _check_source(source, item["sha256"])
    config = request["manifest"]["preprocessing"]
    if not request["ffmpeg"]:
        raise RuntimeError("audio embedding requires installed ffmpeg")
    command = [
        request["ffmpeg"],
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(source),
        "-t",
        str(config["maxSeconds"]),
        "-ac",
        "1",
        "-ar",
        str(config["sampleRate"]),
        "-f",
        "f32le",
        "pipe:1",
    ]
    limit = int(config["maxSeconds"] * config["sampleRate"]) * 4
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(
            command, stdout=output, stderr=errors, timeout=60, check=False
        )
        if result.returncode:
            raise RuntimeError("local embedding audio decode failed")
        output.seek(0)
        data = output.read(limit + 1)
    _check_source(source, item["sha256"])
    if not data or len(data) > limit or len(data) % 4:
        raise RuntimeError("embedding PCM is empty or exceeds its declared budget")
    audio = np.frombuffer(data, dtype="<f4")
    if not np.isfinite(audio).all():
        raise RuntimeError("embedding PCM contains non-finite samples")
    return audio


def _check_source(path, expected):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError("embedding source digest changed")


def _models(request, model_type, processor_type):
    model = (
        model_type.from_pretrained(
            request["modelPath"],
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors="model.safetensors" in request["manifest"]["files"],
            weights_only=True,
        )
        .to(request["device"])
        .eval()
    )
    processor = processor_type.from_pretrained(
        request["modelPath"], local_files_only=True, trust_remote_code=False
    )
    return model, processor


def _inputs(item, request, processor, np):
    config = request["manifest"]["preprocessing"]
    if request["modality"] == "text":
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= 512:
            raise RuntimeError("embedding query must contain 1..512 characters")
        return processor(
            text=[item],
            padding=True,
            truncation=True,
            max_length=config["textMaxLength"],
            return_tensors="pt",
        )
    return processor(
        audios=[_audio(item, request, np)],
        sampling_rate=config["sampleRate"],
        truncation=config["truncation"],
        padding=config["padding"],
        return_tensors="pt",
    )


def _normalized_feature(features, dimension, np, torch):
    if not isinstance(features, torch.Tensor) or features.shape != (1, dimension):
        raise RuntimeError(
            "CLAP output shape is incompatible with the frozen joint space"
        )
    vector = features[0].detach().float().cpu().numpy()
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 0:
        raise RuntimeError("CLAP produced an invalid vector")
    return (vector / norm).tolist()


def execute(request):
    np, torch, model_type, processor_type = _runtime(request)
    if request["action"] == "probe":
        return {
            "jointSpace": request["jointSpace"],
            "validation": "manifest-and-runtime-verified",
            "modelLoaded": False,
        }
    items, modality = request["items"], request["modality"]
    if modality not in {"audio", "text"} or not 1 <= len(items) <= 16:
        raise RuntimeError("embedding batch exceeds its declared budget")
    model, processor = _models(request, model_type, processor_type)
    vectors = []
    for item in items:
        inputs = _inputs(item, request, processor, np)
        inputs = inputs.to(request["device"])
        with torch.inference_mode():
            features = (
                model.get_text_features(**inputs)
                if modality == "text"
                else model.get_audio_features(**inputs)
            )
        vectors.append(
            _normalized_feature(features, request["manifest"]["dimension"], np, torch)
        )
    return {"jointSpace": request["jointSpace"], "vectors": vectors}


if __name__ == "__main__":
    payload = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise RuntimeError("embedding worker input exceeds its byte budget")
    print(json.dumps(execute(json.loads(payload)), allow_nan=False))
