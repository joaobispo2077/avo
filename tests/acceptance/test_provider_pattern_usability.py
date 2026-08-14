from __future__ import annotations

import time
from pathlib import Path

from avo.timeline.animation import AnimationService
from avo.timeline.provider_animation import ProviderAnimationService
from tests.test_animation_promotion import pattern


def test_save_select_and_reject_workflow_under_five_minutes(tmp_path: Path):
    started = time.perf_counter()
    service = ProviderAnimationService(
        tmp_path / "animation.json", provider="bishop",
        clock=lambda: "2026-08-14T00:00:00Z",
    )
    proposal = service.propose(
        pattern(), actor="creator", intent_reference="C01+C02 liked",
    )
    service.decide(
        Path(proposal["path"]), decision="approved",
        actor="creator", reason="sanitized pattern approved",
    )
    catalog = service.load()
    evidence = "e" * 64
    selected = AnimationService.recommend(
        catalog, {"format": "talking-head-review", "constraints": []},
        evidence_sha256=evidence,
    )
    assert selected and selected[0]["patternId"] == "c01-c02"
    service.reject_recommendation(
        pattern_id="c01-c02", evidence_sha256=evidence,
        actor="creator", reason="not for this video",
    )
    assert AnimationService.recommend(
        service.load(), {"format": "talking-head-review", "constraints": []},
        evidence_sha256=evidence,
    ) == []
    serialized = service.path.read_text(encoding="utf-8")
    assert ".mp4" not in serialized and ".png" not in serialized
    assert time.perf_counter() - started < 300
