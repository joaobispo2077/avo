"""Selected specialist exchanges preserve exact dependencies and timeline authority."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import artcraft, init_project
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import _filmcraft_reference_findings
from tests.artcraft_fixtures import locked_tool_observation, picture_output, request
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


def emblem_request(operation, output_role, **changes):
    return request(
        componentId="emblem",
        required={"behavior": operation, "outputRole": output_role, "editable": True},
        **changes,
    )


def emblem_spec(workspace, **changes):
    return job_spec(
        workspace,
        jobId="vector-emblem",
        output={
            "role": "generated-still",
            "format": "svg",
            "alpha": "straight",
            "color": "srgb",
            "width": 128,
            "height": 128,
        },
        **changes,
    )


def animated_emblem_spec(workspace, source_reference, **changes):
    return job_spec(
        workspace,
        jobId="animated-emblem",
        artworkRef=source_reference,
        output=picture_output(
            width=320,
            height=180,
            frameCount=24,
            frameRate={"numerator": 24, "denominator": 1},
        ),
        **{"readRoots": [str(workspace)], **changes},
    )


def _prepare_emblem(spec, adapter, **changes):
    return _prepare(
        artcraft,
        emblem_request("vector-emblem", "generated-still", **changes),
        spec,
        adapter,
        intent=artcraft.ArtCraftIntent("explicit", "vectorcraft", ("vector-emblem",)),
    )


def _prepare_animated_emblem(spec, adapter, **changes):
    return _prepare(
        artcraft,
        emblem_request("animate-vector-emblem", "overlay-video", **changes),
        spec,
        adapter,
        intent=artcraft.ArtCraftIntent(
            "explicit", "anicraft", ("animate-vector-emblem",)
        ),
    )


@pytest.fixture
def vector_export(tmp_path, monkeypatch):
    return make_vector_export(tmp_path, monkeypatch)


def make_vector_export(tmp_path, monkeypatch, *, provider="neutral-channel"):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})

    def observe(*, scope, mode, roots, **_paths):
        return {
            **locked_tool_observation(tmp_path, scope["app"]),
            **scope,
            "mode": mode,
            "effectiveRoots": roots,
        }

    def author(_job, directory):
        directory.mkdir(parents=True)
        files = {
            "nativeSource": directory / "component.vectorcraft",
            "recipe": directory / "recipe.json",
            "media": directory / "emblem.svg",
        }
        for key, path in files.items():
            path.write_text(key, encoding="utf-8")
        return {key: file_fingerprint(path) for key, path in files.items()}

    selected = SimpleNamespace(
        observe=observe, validate_run=lambda _job: None, author_vector_emblem=author
    )
    prepared = _prepare_emblem(
        emblem_spec(tmp_path, provider=provider), selected, provider=provider
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=selected
    )
    reference = artcraft.describe_export_review(
        exported["jobRef"], expected_head=exported["head"]
    )["standalone"]["artworkRef"]
    return selected, exported, reference


def _unexpected_app_access(**_selection):
    pytest.fail("A stale or unrelated dependency must not discover an ArtCraft app")


@pytest.mark.parametrize(
    "altered",
    [
        "foreign-component",
        "wrong-head",
        "outside-read-roots",
        "changed-recipe",
        "changed-tool",
    ],
)
def test_animated_emblem_refuses_stale_or_unrelated_upstream_before_discovery(
    tmp_path, vector_export, altered
):
    _, exported, reference = vector_export
    spec = animated_emblem_spec(tmp_path, reference)
    if altered == "foreign-component":
        source_request = emblem_request("animate-vector-emblem", "overlay-video")
        source_request["componentId"] = "different-emblem"
        scope = artcraft.ArtCraftIntent(
            "explicit", "anicraft", ("animate-vector-emblem",)
        )
        with pytest.raises(
            artcraft.ArtCraftError, match="different provider or component"
        ):
            _prepare(
                artcraft,
                source_request,
                spec,
                SimpleNamespace(observe=_unexpected_app_access),
                intent=scope,
            )
        return
    if altered == "wrong-head":
        reference["exportHead"] = "0" * 64
    if altered == "outside-read-roots":
        spec["readRoots"] = []
    if altered == "changed-recipe":
        _, event = artcraft.read_authoring_export(
            exported["jobRef"], expected_head=exported["head"]
        )
        Path(event["recipe"]["locator"]).write_bytes(b"externally changed")
    if altered == "changed-tool":
        job, _ = artcraft.read_authoring_export(
            exported["jobRef"], expected_head=exported["head"]
        )
        Path(job["observation"]["executable"]["locator"]).write_bytes(
            b"new executable build"
        )
    with pytest.raises(artcraft.ArtCraftError):
        _prepare_animated_emblem(spec, SimpleNamespace(observe=_unexpected_app_access))


def test_animated_emblem_closes_inputs_and_detects_later_source_change(
    tmp_path, vector_export
):
    selected, exported, reference = vector_export
    animated = _prepare_animated_emblem(
        animated_emblem_spec(tmp_path, reference), selected
    )
    job, event = artcraft.read_authoring_export(
        exported["jobRef"], expected_head=exported["head"]
    )
    assert animated["job"]["inputs"] == [
        event["outputs"][0],
        reference["job"],
        event["saved"],
        event["recipe"],
    ]
    assert job["recipeHash"] != animated["job"]["recipeHash"]
    Path(event["saved"]["locator"]).write_bytes(b"different editable source")
    with pytest.raises(artcraft.ArtCraftError, match="prepared job is stale"):
        artcraft.run_authoring(
            animated["jobRef"],
            expected_head=animated["head"],
            adapter=SimpleNamespace(),
        )


@pytest.mark.parametrize("limit", ["files", "bytes"])
def test_animated_emblem_checks_the_combined_input_budget_before_discovery(
    tmp_path, vector_export, limit
):
    _, exported, reference = vector_export
    _, event = artcraft.read_authoring_export(
        exported["jobRef"], expected_head=exported["head"]
    )
    dependencies = [
        reference["job"],
        event["saved"],
        event["recipe"],
        *event["outputs"],
    ]
    specs = animated_emblem_spec(tmp_path, reference)
    spec_budget = specs["budget"]
    spec_budget[limit] = (
        len(dependencies) - 1
        if limit == "files"
        else sum(item["sizeBytes"] for item in dependencies) - 1
    )
    with pytest.raises(artcraft.ArtCraftError, match="inputs exceed.*budget"):
        _prepare_animated_emblem(specs, SimpleNamespace(observe=_unexpected_app_access))
    assert not (tmp_path / "artcraft-jobs" / "job-animated-emblem").exists()
