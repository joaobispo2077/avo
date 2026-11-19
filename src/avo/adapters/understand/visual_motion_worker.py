"""Standalone CPU model probe for the optional isolated visual runtime."""

import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory


def _probe(model_path, expected_hash):
    import cv2
    import numpy as np

    with Path(model_path).open("rb") as stream:
        model = stream.read(232590)
    if len(model) != 232589 or hashlib.sha256(model).hexdigest() != expected_hash:
        raise ValueError("YuNet model bytes changed before loading")
    cv2.setNumThreads(1)
    with TemporaryDirectory(prefix="avo-visual-") as directory:
        admitted = Path(directory) / "yunet.onnx"
        admitted.write_bytes(model)
        detector = cv2.FaceDetectorYN.create(
            str(admitted),
            "",
            (320, 320),
            0.8,
            0.3,
            5000,
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )
        _, output = detector.detect(np.zeros((320, 320, 3), dtype=np.uint8))
    if output is not None:
        raise ValueError("The model probe returned observations on a blank frame")
    return {
        "modelSha256": expected_hash,
        "isolated": sys.flags.isolated == 1 and sys.prefix != sys.base_prefix,
        "versions": {key: version(key) for key in ("opencv-python-headless", "numpy")},
        "device": "cpu",
    }


if __name__ == "__main__":
    print(json.dumps(_probe(*sys.argv[1:])))
