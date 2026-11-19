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

The capture adapter decodes one selected original video stream over a range of
up to 30 seconds. It verifies the original bytes and reads the selected frame
timestamps directly from FFmpeg. The proxy keeps the original display aspect
after rotation and pixel aspect correction. Preparation accepts up to 300
frames and 64 MiB of proxy data. A longer range of samples can use a larger
frame stride. The worker checks the proxy hash before detection.

The observation record binds the selected source range, exact frame timestamps,
display geometry, detector versions, face boxes and association coverage. It
also freezes the selected path with a three-sample median of interior center
points. The first and last measured centers stay exact. The native stream
origin is retained when available, and half-open uncertainty intervals identify
the source ticks outside the measured path. These intervals remain pending
framing review.

Use `avo cli animation face-analyze --project <absolute-project>`
`--request <request.json> --json` for an explicit analysis. The request names
the current canonical basis, original source fingerprint, exact video stream,
source range, sampling stride and selected sampled detection. Its editing craft
selection enables camera and selected-subject face anchoring. MCP confirms the
exact request bytes before executing. The resulting observation is saved under
`edit/motion/face/` for review and keeps the current camera edit in place. The
command returns the trajectory hash and uncertainty intervals with the saved
observation reference.

To use the path, attach `faceAnchor` to the selected camera recipe with the
returned `observationRef` and `trajectoryHash`, plus `transitionFrames` from 1
through 60. The camera option `faceAnchor: selected-subject` stays opt-in. AVO
uses the transition to enter and release face framing within the selected recipe.
A cut-to-close entry still needs a visible source cut. Each face-anchored cue
uses 2–256 exact frames from one original-source occurrence on its native clock.

If a cue uses uncertain frames, `onLost: review` stops proof compilation for
judgment. Select `hold` to hold the last qualified framing or `static` to return
to the baseline crop. Both choices require `faceAnchor.fallbackReview` with the
actor and reason. The linked map and storyboard show the measured source range,
uncertain intervals and fallback status. AVO checks the selected evidence when
publishing and admitting a proof, and seeking uses the frozen camera path.

## Selected reference ranges

Run `avo cli animation reference-analyze --project <absolute-project>`
`--request <request.json> --json` for explicit reference measurements. The
request binds the current project basis, enables `referenceAnalysis`, supplies
the absolute isolated `runtimePython` path and selects each local original
by size, digest, stream, native source range, frame stride and desired aspects.
Reference feature tracking runs with the pinned OpenCV and NumPy environment
alone.

The default processing budget allows ten clips and 300 seconds total, with
each range at most 30 seconds. An explicit budget can raise the total to 20
clips and 600 seconds. Each successful clip returns its measured coverage and a
PNG with up to six frames labeled by original presentation timestamp. The
inspection record and sheets live under `edit/motion/references/`.

Global movement estimates report scale, rotation in degrees and frame-center
translation as fractions of display width and height. Residual movement uses
the display diagonal. Brightness uses normalized mean grayscale. Cuts are
candidates between sampled frames. Dark or poorly tracked intervals stay
unmeasurable. Easing interpretation and any unavailable hold/reveal or
audio/word evidence are reported separately from observed frame measurements.
[OpenCV feature tracking](https://docs.opencv.org/4.12.0/dc/d6b/group__video__track.html)

After inspecting a clip, use `avo cli animation reference-decide` with a
new exact request to record `accept`, `qualify` or `reject`. Accept and qualify
require the selected measured aspects. Qualify also records a usage limit.
The decision stores a project-scoped descriptor for Briefstart. Provide its
path explicitly as a reference when preparing a brief. Briefstart checks the
provider, project identity and inspection digest before consuming the document.
