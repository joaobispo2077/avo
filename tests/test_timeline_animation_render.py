from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from avo.adapters.base import JobResult
from avo.adapters.motion.hyperframes import HyperframesAdapter, HyperframesError
from avo.timeline.contracts import file_fingerprint


class FakeHyperframes(HyperframesAdapter):
    def execute(self, operation, project, *extra, root=None):
        if operation == "render":
            output = Path(extra[extra.index("--output") + 1])
            output.write_bytes(b"rendered-animation")
            return JobResult(exit_code=0, artifact_paths=[output])
        return JobResult(exit_code=0)


def test_hashed_seek_safe_instance_render_contract():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        (project / "index.html").write_text(
            "<div data-composition-id='x'></div>", encoding="utf-8"
        )
        output = root / "animation.mp4"
        result = FakeHyperframes().render_timeline_instance(
            project=project,
            output=output,
            instance={
                "componentRef": "chapter-pair",
                "bmapCueId": "cue-one",
                "placement": {"layerId": "graphics", "x": 0.1, "y": 0.2},
                "range": {"startTicks": 100, "endTicks": 500},
                "reducedMotion": False,
            },
            component_contract={
                "lifecycle": {
                    "preEntry": "hidden",
                    "entrance": "in",
                    "hold": "read",
                    "exit": "out",
                }
            },
        )
        assert len(result["output"]["sha256"]) == 64
        assert result["bmapCueId"] == "cue-one"


def test_nondeterministic_source_blocks_before_check():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        project.mkdir()
        (project / "index.html").write_text(
            "<script>Math.random()</script>", encoding="utf-8"
        )
        with pytest.raises(HyperframesError, match="nondeterministic"):
            FakeHyperframes().render_timeline_instance(
                project=project,
                output=Path(tmp) / "out.mp4",
                instance={
                    "componentRef": "x",
                    "bmapCueId": "q",
                    "placement": {},
                    "range": {},
                    "reducedMotion": False,
                },
                component_contract={"lifecycle": {"preEntry": "x"}},
            )


def _instance():
    return {
        "componentRef": "chapter",
        "bmapCueId": "chapter-cue",
        "placement": {},
        "range": {"startFrame": 0, "endFrameExclusive": 2},
        "reducedMotion": False,
    }


def test_frozen_vendor_runtime_and_explicit_png_capture(tmp_path):
    project = tmp_path / "project"
    (project / "lib").mkdir(parents=True)
    (project / "index.html").write_text("<div>Chapter</div>", encoding="utf-8")
    runtime = project / "lib" / "runtime.js"
    runtime.write_text("// https://vendor.example\nMath.random;", encoding="utf-8")
    calls = []

    class Frames(FakeHyperframes):
        def execute(self, operation, project, *extra, root=None):
            calls.append((operation, extra))
            if operation == "render":
                output = Path(extra[extra.index("--output") + 1])
                output.mkdir()
                (output / "frame-000000.png").write_bytes(b"captured-frame")
            return JobResult(exit_code=0)

    output = tmp_path / "frames"
    result = Frames().render_timeline_instance(
        project=project,
        output=output,
        instance=_instance(),
        component_contract={
            "lifecycle": {"preEntry": "hidden"},
            "runtimeDependencies": [
                {
                    "path": "lib/runtime.js",
                    "sha256": file_fingerprint(runtime)["sha256"],
                }
            ],
            "renderContract": {"frameRate": {"num": 60, "den": 1}},
        },
        output_format="png-sequence",
    )
    assert calls[0] == ("check", ("--strict", "--no-browser-gpu"))
    assert calls[1][1][-6:] == (
        "--format",
        "png-sequence",
        "--no-browser-gpu",
        "--no-best-effort",
        "--fps",
        "60/1",
    )
    assert result["output"]["frames"] == [file_fingerprint(output / "frame-000000.png")]


@pytest.mark.parametrize("fault", ["changed", "unlisted", "outside-library"])
def test_frozen_vendor_runtime_does_not_bypass_source_checks(tmp_path, fault):
    project = tmp_path / "project"
    (project / "lib").mkdir(parents=True)
    (project / "index.html").write_text("<div>Chapter</div>", encoding="utf-8")
    runtime = project / (
        "author.js" if fault == "outside-library" else "lib/runtime.js"
    )
    runtime.write_text("Math.random()", encoding="utf-8")
    contract = {
        "lifecycle": {"preEntry": "hidden"},
        "runtimeDependencies": [
            {"path": str(runtime), "sha256": file_fingerprint(runtime)["sha256"]}
        ],
    }
    if fault == "changed":
        runtime.write_text("Math.random();changed()", encoding="utf-8")
    elif fault == "unlisted":
        contract["runtimeDependencies"] = []
    output = tmp_path / "must-not-render.mp4"
    with pytest.raises(HyperframesError, match="dependency|nondeterministic"):
        FakeHyperframes().render_timeline_instance(
            project=project,
            output=output,
            instance=_instance(),
            component_contract=contract,
        )
    assert not output.exists()
