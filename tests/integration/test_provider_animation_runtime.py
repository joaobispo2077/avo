from __future__ import annotations

from pathlib import Path

from tests.test_animation_promotion import pattern

from avo.adapters.base import JobResult
from avo.adapters.motion.hyperframes import HyperframesAdapter
from avo.timeline.animation import AnimationService
from avo.timeline.provider_animation import ProviderAnimationService


class RenderFixture(HyperframesAdapter):
    def execute(self, operation, project, *extra, root=None):
        if operation == "render":
            output = Path(extra[extra.index("--output") + 1])
            output.write_bytes(b"fresh-video-specific-c01-c02-render")
            return JobResult(exit_code=0, artifact_paths=[output])
        return JobResult(exit_code=0)


def test_c01_c02_promote_recommend_and_render_new_instance(tmp_path: Path):
    catalog_path = tmp_path / "providers" / "bishop" / "animations" / "animation.json"
    service = ProviderAnimationService(
        catalog_path,
        provider="bishop",
        clock=lambda: "2026-08-13T12:00:00Z",
    )
    proposal = service.propose(
        pattern(),
        actor="creator",
        intent_reference="C01 and C02 were awesome; store pattern",
    )
    assert not catalog_path.exists()
    service.decide(
        Path(proposal["path"]),
        decision="approved",
        actor="creator",
        reason="generalized sanitized pattern reviewed",
    )
    catalog = service.load()
    serialized = catalog_path.read_text(encoding="utf-8")
    assert "Splatoon Raiders" not in serialized
    assert ".png" not in serialized and ".mp4" not in serialized
    recommendations = AnimationService.recommend(
        catalog,
        {"format": "talking-head-review", "viewerIntent": "decide", "constraints": []},
        evidence_sha256="c" * 64,
    )
    assert [item["patternId"] for item in recommendations] == ["c01-c02"]

    project = tmp_path / "new-video-animation"
    project.mkdir()
    (project / "index.html").write_text(
        "<div data-composition-id='chapter-pair' data-duration='3'></div>",
        encoding="utf-8",
    )
    output = tmp_path / "new-video-c01-c02.mp4"
    result = RenderFixture().render_timeline_instance(
        project=project,
        output=output,
        instance={
            "componentRef": "chapter-pair",
            "bmapCueId": "new-video-cue",
            "placement": {"layerId": "graphics", "x": 0.05, "y": 0.08},
            "range": {"startTicks": 180000, "endTicks": 360000},
            "reducedMotion": False,
        },
        component_contract={
            "lifecycle": {
                "preEntry": "hidden",
                "entrance": "tremble",
                "hold": "readable",
                "exit": "resolve",
            }
        },
    )
    assert output.is_file()
    assert len(result["output"]["sha256"]) == 64
    assert result["bmapCueId"] == "new-video-cue"
