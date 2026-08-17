from __future__ import annotations

import time

from avo.timeline.contracts import content_hash


def test_canonical_hash_ten_thousand_items_under_two_seconds():
    document = {
        "items": [
            {
                "cueId": f"cue-{index:05d}",
                "ticks": index * 1000,
                "reason": "deterministic performance fixture",
            }
            for index in range(10_000)
        ]
    }
    started = time.perf_counter()
    first = content_hash(document)
    elapsed = time.perf_counter() - started
    assert len(first) == 64
    assert elapsed < 2.0
    assert content_hash(document) == first


def test_unchanged_materialization_skips_renderer_and_mutation_forces_it(tmp_path):
    from avo.timeline.cmap_service import CMapService
    from avo.timeline.materialize import materialize_cut_proof
    from tests.test_timeline_cmap_service import snapshot, workspace
    from tests.test_timeline_render_port import FakeRender

    ws = workspace(tmp_path)
    raw = ws.raw_dir / "raw.bin"
    raw.write_bytes(b"raw")
    revision = CMapService(ws).author(
        snapshot(raw), actor="agent", reason="performance reuse"
    )
    output = ws.raw_dir / "edit" / "proof.mp4"
    renderer = FakeRender()
    first = materialize_cut_proof(
        workspace=ws,
        cmap_revision_id=revision["revisionId"],
        output_path=output,
        render_port=renderer,
    )
    second = materialize_cut_proof(
        workspace=ws,
        cmap_revision_id=revision["revisionId"],
        output_path=output,
        render_port=renderer,
    )
    assert first == second
    assert len(renderer.calls) == 1

    output.write_bytes(b"other")
    materialize_cut_proof(
        workspace=ws,
        cmap_revision_id=revision["revisionId"],
        output_path=output,
        render_port=renderer,
    )
    assert len(renderer.calls) == 2
