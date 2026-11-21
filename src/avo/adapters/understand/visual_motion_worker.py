"""Standalone CPU analysis for verified frames in a prepared display proxy."""

import hashlib
import json
import sys
from importlib.metadata import version
from itertools import pairwise
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
        **({"modelSha256": expected_hash} if expected_hash is not None else {}),
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


def _tracked_points(before, after):
    import cv2
    import numpy as np

    corners = cv2.goodFeaturesToTrack(before, 160, 0.015, 5, blockSize=5)
    if corners is None or len(corners) < 12:
        return None
    forward, found, _ = cv2.calcOpticalFlowPyrLK(before, after, corners, None)
    backward, returned, _ = cv2.calcOpticalFlowPyrLK(after, before, forward, None)
    reversibility = np.linalg.norm((backward - corners).reshape(-1, 2), axis=1)
    good = (found.ravel() == 1) & (returned.ravel() == 1) & (reversibility <= 1.25)
    return corners.reshape(-1, 2)[good], forward.reshape(-1, 2)[good]


def _global_fit(before, after):
    import cv2
    import numpy as np

    matrix, mask = cv2.estimateAffinePartial2D(
        before, after, method=cv2.RANSAC, ransacReprojThreshold=1.5, maxIters=1000
    )
    if matrix is None or mask is None or not np.isfinite(matrix).all():
        return None
    inliers = mask.ravel().astype(bool)
    if inliers.sum() < 12 or inliers.mean() < 0.65:
        return None
    return matrix, inliers


def _motion_values(tracked, fit, size):
    import numpy as np

    before, after = tracked
    matrix, inliers = fit
    width, height = size
    spread = np.ptp(before[inliers], axis=0) / (width, height)
    if np.min(spread) < 0.4:
        return None
    center = np.array([width / 2, height / 2])
    movement = (matrix[:, :2] @ center + matrix[:, 2] - center) / (width, height)
    predicted = before @ matrix[:, :2].T + matrix[:, 2]
    residual = np.linalg.norm(after - predicted, axis=1)
    return {
        "global": {
            "scale": float(np.hypot(matrix[0, 0], matrix[1, 0])),
            "rotationDegrees": float(
                np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0]))
            ),
            "translateX": float(movement[0]),
            "translateY": float(movement[1]),
        },
        "coverage": {
            "tracked": len(before),
            "inliers": int(inliers.sum()),
            "spanX": float(spread[0]),
            "spanY": float(spread[1]),
        },
        "residual": {
            "p90DisplayDiagonal": float(
                np.percentile(residual, 90) / np.hypot(width, height)
            ),
            "movingPoints": int(np.count_nonzero(residual > 1.5)),
        },
    }


def _histogram_distance(before, after):
    import cv2

    histograms = [
        cv2.calcHist([frame], [0], None, [32], [0, 256]) for frame in (before, after)
    ]
    return cv2.compareHist(*histograms, cv2.HISTCMP_BHATTACHARYYA)


def _attempt_motion(before, after):
    import cv2

    if min(before.mean(), after.mean()) < 8:
        return {"status": "unmeasurable", "reason": "dark-frame"}
    detail = min(cv2.Laplacian(frame, cv2.CV_64F).var() for frame in (before, after))
    if detail < 12:
        return {"status": "unmeasurable", "reason": "insufficient-detail"}
    tracked = _tracked_points(before, after)
    fit = (
        _global_fit(*tracked) if tracked is not None and len(tracked[0]) >= 12 else None
    )
    motion = (
        _motion_values(tracked, fit, before.shape[::-1]) if fit is not None else None
    )
    if motion is not None:
        return {"status": "measured", **motion}
    if _histogram_distance(before, after) > 0.45:
        return {
            "status": "cut-candidate",
            "reason": "tracking-break-and-histogram-change",
        }
    return {"status": "unmeasurable", "reason": "unqualified-global-motion"}


def _reference_motion(path, width, height, count, proxy_hash):
    import cv2
    import numpy as np

    width, height, count = map(int, (width, height, count))
    if count < 2:
        raise ValueError("Reference motion needs at least two sampled frames")
    raw = _proxy_bytes(path, width, height, count, proxy_hash)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(count, height, width, 3)
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    cv2.ocl.setUseOpenCL(False)
    gray = (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames)
    return {
        **_identity(None),
        "proxySha256": proxy_hash,
        "method": "pyramidal-lk-partial-affine-v1",
        "pairs": [
            {
                **_attempt_motion(before, after),
                "brightness": {
                    "before": float(before.mean() / 255),
                    "after": float(after.mean() / 255),
                },
            }
            for before, after in pairwise(gray)
        ],
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["reference-motion"]:
        report = _reference_motion(*args[1:])
    else:
        action = _probe if len(args) == 2 else _detect
        report = action(*args)
    print(json.dumps(report, allow_nan=False))
