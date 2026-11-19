"""Verify an explicitly prepared local CPU face detector."""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_BYTES = 232589
VERSIONS = {"opencv-python-headless": "4.12.0.88", "numpy": "2.2.6"}


def _local_file(value, name):
    path = Path(value or "")
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"Face analysis needs a prepared local {name}")
    return path.resolve()


def _verify_model(path):
    with path.open("rb") as stream:
        raw = stream.read(YUNET_BYTES + 1)
    if len(raw) != YUNET_BYTES or hashlib.sha256(raw).hexdigest() != YUNET_SHA256:
        raise ValueError(
            "Face analysis requires the exact pinned YuNet 2023 model bytes"
        )


def _probe(python, model):
    worker = (
        Path(__file__).parent / "adapters" / "understand" / "visual_motion_worker.py"
    )
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(
            [str(python), "-I", str(worker), str(model), YUNET_SHA256],
            stdout=output,
            stderr=errors,
            check=False,
            timeout=30,
        )
        if result.returncode:
            errors.seek(0)
            detail = errors.read(1024).decode("utf-8", errors="replace")
            raise ValueError(f"Face runtime probe failed: {detail}")
        output.seek(0)
        data = output.read(4097)
    if len(data) > 4096:
        raise ValueError("Face runtime probe exceeds its output budget")
    return json.loads(data)


def preflight_face_job(resolved):
    source = resolved.pin.get("source") or {}
    runtime = resolved.pin.get("runtime") or {}
    if resolved.id != "yunet-2023mar" or source.get("kind") != "artifact":
        raise ValueError("Face analysis needs the pinned YuNet 2023 local artifact")
    if (
        runtime.get("device", "cpu") != "cpu"
        or runtime.get("allowDownload")
        or runtime.get("offline") is False
    ):
        raise ValueError("Face analysis requires an offline CPU runtime")
    model = _local_file(source.get("artifactPath"), "YuNet model")
    _verify_model(model)
    python = _local_file(runtime.get("pythonEnv"), "isolated Python interpreter")
    if python == Path(sys.executable).resolve():
        raise ValueError("Face analysis needs a separate Python environment")
    report = _probe(python, model)
    if report != {
        "device": "cpu",
        "isolated": True,
        "modelSha256": YUNET_SHA256,
        "versions": VERSIONS,
    }:
        raise ValueError(
            "Face runtime differs from the pinned isolated CPU environment"
        )
    return report
