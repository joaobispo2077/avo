from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from avo.adapters.base import JobResult
from avo.adapters.motion.hyperframes import HyperframesAdapter, HyperframesError


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
