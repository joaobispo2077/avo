"""Standalone CPU detector for verified frames in a prepared display proxy."""

import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory


def _detector(model_path, expected_hash, width, height):
    import cv2

    with Path(model_path).open("rb") as stream:
        model = stream.read(232590)
    if len(model) != 232589 or hashlib.sha256(model).hexdigest() != expected_hash:
        raise ValueError("YuNet model bytes changed before loading")
    cv2.setNumThreads(1)
    with TemporaryDirectory(prefix="avo-visual-") as directory:
        admitted = Path(directory) / "yunet.onnx"
        admitted.write_bytes(model)
        return cv2.FaceDetectorYN.create(
            str(admitted),
            "",
            (width, height),
            0.8,
            0.3,
            5000,
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )


def _identity(expected_hash):
    return {
        "modelSha256": expected_hash,
        "isolated": sys.flags.isolated == 1 and sys.prefix != sys.base_prefix,
        "versions": {key: version(key) for key in ("opencv-python-headless", "numpy")},
        "device": "cpu",
    }


def _probe(model_path, expected_hash):
    import numpy as np

    detector = _detector(model_path, expected_hash, 320, 320)
    _, output = detector.detect(np.zeros((320, 320, 3), dtype=np.uint8))
    if output is not None:
        raise ValueError("The model probe returned observations on a blank frame")
    return _identity(expected_hash)


def _proxy_bytes(path, width, height, count, expected_hash):
    size = width * height * 3 * count
    if not (
        32 <= width <= 640
        and 32 <= height <= 640
        and 1 <= count <= 300
        and size <= 64 * 1024 * 1024
    ):
        raise ValueError("Face proxy exceeds frame or byte limits")
    with Path(path).open("rb") as stream:
        data = stream.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError("Face proxy bytes differ from the pinned input")
    return data


def _detect_frame(detector, frame):
    _, found = detector.detect(frame)
    if found is None:
        return []
    if found.ndim != 2 or found.shape[1] != 15 or len(found) > 32:
        raise ValueError("Face detector returned unsupported or too many observations")
    return [{"box": row[:4], "score": row[14]} for row in found.tolist()]


def _detect(model_path, expected_hash, path, width, height, count, proxy_hash):
    import numpy as np

    width, height, count = map(int, (width, height, count))
    raw = _proxy_bytes(path, width, height, count, proxy_hash)
    detector = _detector(model_path, expected_hash, width, height)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(count, height, width, 3)
    return {
        **_identity(expected_hash),
        "proxySha256": proxy_hash,
        "detections": [_detect_frame(detector, frame) for frame in frames],
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    action = _probe if len(args) == 2 else _detect
    print(json.dumps(action(*args), allow_nan=False))
