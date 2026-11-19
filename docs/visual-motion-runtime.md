# Optional face detector runtime

AVO can verify an explicitly configured local YuNet CPU detector. The
`models_cli preflight face_detect` command checks the official model bytes and
probes a separate Python environment. A successful result means the detector
loaded and processed a blank frame. Source analysis and camera application
are separate stages.

The qualified environment uses Windows x64 and Python 3.11. Install
[OpenCV headless 4.12.0.88](https://pypi.org/project/opencv-python-headless/4.12.0.88/)
and [NumPy 2.2.6](https://pypi.org/project/numpy/2.2.6/) in a separate virtual
environment using the checked-in [wheel hashes](../config/visual-motion-cpu-windows.requirements.txt)
with `uv pip install --require-hashes -r <requirements> --python <interpreter>`.
The detector and its dependencies are provisioned separately from the AVO engine.

Prepare the [YuNet 2023 model](https://github.com/opencv/opencv_zoo/blob/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx)
at the pinned upstream revision. The ONNX file is 232,589 bytes with SHA-256
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
OpenCV and NumPy carry their own package notices. YuNet has a separate
[MIT notice](https://github.com/opencv/opencv_zoo/blob/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/LICENSE).

The existing model settings accept a local `models.face_detect` pin:

```json
{
  "id": "yunet-2023mar",
  "source": {
    "kind": "artifact",
    "artifactPath": "H:/models/face_detection_yunet_2023mar.onnx"
  },
  "runtime": {
    "device": "cpu",
    "offline": true,
    "allowDownload": false,
    "pythonEnv": "H:/models/visual-cpu/Scripts/python.exe"
  }
}
```

Use the actual prepared paths. Run `avo models_cli preflight face_detect --json`
to check the selected global pin. Checkout users can run
`python -m avo.models_cli preflight face_detect --json`.

Face observations support geometric association from an explicitly selected
box. A missing face, competing overlaps or a gap leaves the association
unresolved until the creator selects a new seed.
