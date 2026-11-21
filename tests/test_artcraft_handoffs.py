"""FilmCraft exchange evidence stays separate from canonical activation."""

from copy import deepcopy

import pytest

from avo import artcraft, init_project
from avo.timeline.import_service import _filmcraft_reference_findings
from tests.artcraft_fixtures import request
from tests.test_artcraft_jobs import _prepare, job_spec


def film_request(provider):
    return request(
        provider=provider,
        required={
            "behavior": "source-linked-timeline-return",
            "outputRole": "timeline-interchange",
            "editable": True,
        },
    )


def film_spec(path, original, **overrides):
    return job_spec(
        path,
        readRoots=[str(original.parent)],
        interchangeSource={"source": str(original), "width": 320, "height": 180},
        output={
            "role": "timeline-interchange",
            "format": "otio",
            "frameRate": {"numerator": 24, "denominator": 1},
            "frameCount": 24,
        },
        **overrides,
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("loss", "FILMCRAFT_EXCHANGE_LOSS"),
        ("effect", "FILMCRAFT_UNSUPPORTED_TREATMENT"),
        ("reference", "FILMCRAFT_ORIGINAL_MISMATCH"),
    ],
)
def test_filmcraft_requires_source_relationships_and_reports_exchange_losses(
    tmp_path, mutation, expected
):
    original = tmp_path / "camera.mov"
    inventory = {
        "truncated": False,
        "findings": [],
        "summary": {
            "tracks": 2,
            "clips": 2,
            "markers": 0,
            "effects": 0,
            "gaps": 0,
            "transitions": 0,
        },
        "references": [
            {"targetUrl": "camera.mov", "pointer": f"/clip/{index}"}
            for index in range(2)
        ],
    }
    assert not _filmcraft_reference_findings(inventory, tmp_path, original, [])
    altered = deepcopy(inventory)
    losses = []
    if mutation == "loss":
        losses.append("The native editor omitted a clip treatment")
    if mutation == "effect":
        altered["summary"]["effects"] = 1
    if mutation == "reference":
        altered["references"][0]["targetUrl"] = "different.mov"
    assert (
        _filmcraft_reference_findings(altered, tmp_path, original, losses)[0]["code"]
        == expected
    )


def test_filmcraft_rejects_complete_proof_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    directory = tmp_path / "proof"
    directory.mkdir()
    original = directory / "render.mp4"
    original.write_bytes(b"not an original")
    intent = artcraft.ArtCraftIntent(
        "explicit", "filmcraft", ("source-linked-timeline-return",)
    )
    spec = film_spec(tmp_path, original)
    with pytest.raises(artcraft.ArtCraftError, match="program proof"):
        _prepare(artcraft, film_request(spec["provider"]), spec, None, intent=intent)
