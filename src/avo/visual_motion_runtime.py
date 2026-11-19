"""Verify an explicitly prepared local CPU face detector."""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from avo.reference_analysis import SCHEMA
from avo.timeline.contracts import validate_document

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


def _run_worker(python, model, *arguments, timeout=30, output_limit=4096):
    worker = (
        Path(__file__).parent / "adapters" / "understand" / "visual_motion_worker.py"
    )
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(
            [str(python), "-I", str(worker), str(model), YUNET_SHA256, *arguments],
            stdout=output,
            stderr=errors,
            check=False,
            timeout=timeout,
        )
        if result.returncode:
            errors.seek(0)
            detail = errors.read(1024).decode("utf-8", errors="replace")
            raise ValueError(f"Face runtime failed: {detail}")
        output.seek(0)
        data = output.read(output_limit + 1)
    if len(data) > output_limit:
        raise ValueError("Face runtime exceeds its output budget")
    return json.loads(data)


def _runtime_paths(resolved):
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
    return python, model


def _require_runtime_identity(report):
    expected = {
        "device": "cpu",
        "isolated": True,
        "modelSha256": YUNET_SHA256,
        "versions": VERSIONS,
    }
    if not isinstance(report, dict) or any(
        report.get(key) != value for key, value in expected.items()
    ):
        raise ValueError(
            "Face runtime differs from the pinned isolated CPU environment"
        )


def preflight_face_job(resolved):
    report = _run_worker(*_runtime_paths(resolved))
    _require_runtime_identity(report)
    return report


def detect_proxy_faces(resolved, proxy_path, *, width, height, frame_count, sha256):
    """Run an explicit local detector on exact bounded BGR display frames."""
    proxy = _local_file(proxy_path, "display proxy")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(digit not in "0123456789abcdef" for digit in sha256)
    ):
        raise ValueError("The display proxy needs an exact SHA-256")
    report = _run_worker(
        *_runtime_paths(resolved),
        str(proxy),
        str(width),
        str(height),
        str(frame_count),
        sha256,
        timeout=120,
        output_limit=2 * 1024 * 1024,
    )
    _require_runtime_identity(report)
    rows = report.get("detections")
    validate_document(rows, SCHEMA + "#/$defs/proxyDetectionRows")
    if report.get("proxySha256") != sha256 or len(rows) != frame_count:
        raise ValueError("Face observations differ from the prepared display proxy")
    return report


__all__ = ["detect_proxy_faces", "preflight_face_job"]
