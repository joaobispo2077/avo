"""Opt-in checks against explicitly selected local ArtCraft installations."""

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image, ImageCms
from tests.test_artcraft_profiles import (
    effect_spec,
    photo_spec,
    prepare_deck,
    prepare_effect,
    prepare_fig,
    prepare_light,
    prepare_photo,
    static_review_spec,
)

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.timeline.artcraft_stills import read_generated_still
from avo.timeline.contracts import file_fingerprint

pytestmark = [pytest.mark.integration, pytest.mark.native_artcraft]


@pytest.fixture
def photocraft_adapter(tmp_path):
    return _installed_adapter(
        tmp_path, "AVO_ARTCRAFT_PHOTOCRAFT_TEST_CLI", "PhotoCraft 0.23.1"
    )


@pytest.fixture
def figcraft_adapter(tmp_path):
    return _installed_adapter(
        tmp_path, "AVO_ARTCRAFT_FIGCRAFT_TEST_CLI", "FigCraft 0.18.1"
    )


@pytest.fixture
def deckcraft_adapter(tmp_path):
    return _installed_adapter(
        tmp_path, "AVO_ARTCRAFT_DECKCRAFT_TEST_CLI", "DeckCraft 0.18.1"
    )


@pytest.fixture
def lightcraft_adapter(tmp_path):
    return _installed_adapter(
        tmp_path, "AVO_ARTCRAFT_LIGHTCRAFT_TEST_CLI", "LightCraft 0.21.1"
    )


@pytest.fixture
def effectcraft_adapter(tmp_path):
    if not os.environ.get("AVO_ARTCRAFT_EFFECTCRAFT_TEST_CLI"):
        pytest.skip(
            "set AVO_ARTCRAFT_EFFECTCRAFT_TEST_CLI to the installed Windows EffectCraft 0.24.1 CLI"
        )
    font = (Path(os.environ["SystemRoot"]) / "Fonts" / "arial.ttf").resolve(strict=True)
    executable, adapter = _installed_adapter(
        tmp_path,
        "AVO_ARTCRAFT_EFFECTCRAFT_TEST_CLI",
        "EffectCraft 0.24.1",
        permitted_read=(font.parent,),
    )
    return executable, adapter, font


def _installed_adapter(tmp_path, variable, product, *, permitted_read=()):
    entry = os.environ.get(variable)
    if not entry:
        pytest.skip(f"set {variable} to the installed Windows {product} CLI")
    executable = Path(entry).resolve(strict=True)

    def observe(_installed, roots):
        assert all(
            Path(root).is_relative_to(tmp_path) or Path(root) in permitted_read
            for root in roots["read"]
        )
        assert all(Path(root).is_relative_to(tmp_path) for root in roots["write"])
        return roots

    def run(binary, roots, directory, arguments, *, env, timeout):
        assert binary["locator"] == str(executable)
        assert roots["write"] == [str(directory)]
        return subprocess.run(
            [str(executable), *map(str, arguments)],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    return executable, SelectedArtCraftAdapter(
        observe_confinement=observe, run_confined=run
    )


def test_native_photocraft_retains_an_editable_image_for_review(
    tmp_path, monkeypatch, photocraft_adapter
):
    executable, adapter = photocraft_adapter
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    source = tmp_path / "photo.png"
    _synthetic_photo(source)
    original = file_fingerprint(source)
    prepared = prepare_photo(
        photo_spec(tmp_path, source, cliPath=str(executable)),
        adapter,
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert job["inputs"] == [original] == [file_fingerprint(source)]
    assert job["observation"]["release"] == "0.23.1"
    assert Path(event["saved"]["locator"]).name == "component.pcraft"
    with (
        Image.open(source) as initial,
        Image.open(event["outputs"][0]["locator"]) as rendered,
    ):
        assert initial.getpixel((100, 70)) != rendered.getpixel((100, 70))
        assert initial.getchannel("A").tobytes() == rendered.getchannel("A").tobytes()
        assert initial.info["icc_profile"] == rendered.info["icc_profile"]
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["reviewState"] == "pending-creator"
    assert review["standalone"]["admission"] == "standalone-review"
    assert "generatedStillRef" not in review["standalone"]
    with pytest.raises(ValueError, match="verified VectorCraft card"):
        read_generated_still(
            {
                "job": file_fingerprint(Path(prepared["jobRef"])),
                "exportHead": exported["head"],
            }
        )


def _synthetic_photo(path):
    image = Image.new("RGBA", (320, 180))
    image.putdata(
        [
            (x * 255 // 320, y * 255 // 180, 106, 140 if x < 40 else 255)
            for y in range(180)
            for x in range(320)
        ]
    )
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    image.save(path, icc_profile=profile.tobytes())


def test_native_figcraft_retains_editable_layout_and_prototype_for_review(
    tmp_path, monkeypatch, figcraft_adapter
):
    executable, adapter = figcraft_adapter
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    prepared = prepare_fig(
        static_review_spec(tmp_path, cliPath=str(executable)), adapter
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert job["observation"]["release"] == "0.18.1"
    assert job["inputs"] == []
    assert Path(event["saved"]["locator"]).name == "component.figcraft"
    with Image.open(event["outputs"][0]["locator"]) as image:
        assert image.info["srgb"] == 0
        assert image.size == (320, 180)
        assert image.getpixel((40, 40)) == (250, 204, 21, 255)
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["standalone"]["admission"] == "standalone-review"
    assert "click-to-switch prototype" in review["standalone"]["losses"][0]
    assert "generatedStillRef" not in review["standalone"]
    _assert_figcraft_root_rejection(
        executable, tmp_path, Path(event["saved"]["locator"])
    )


def _assert_figcraft_root_rejection(executable, tmp_path, source):
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    script = restricted / "inspect.json"
    script.write_text("[]", encoding="utf-8")
    forbidden_copy = restricted / "denied.figcraft"
    response = subprocess.run(
        [
            str(executable),
            "run",
            str(script),
            "--no-system-fonts",
            "--in",
            str(source),
            "--out",
            str(forbidden_copy),
            "--automation-read-root",
            str(restricted),
            "--automation-write-root",
            str(restricted),
        ],
        cwd=restricted,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=8,
    )
    assert response.returncode != 0
    assert b"read" in response.stderr.lower()
    assert not forbidden_copy.exists()


def test_native_deckcraft_retains_master_and_transition_for_static_review(
    tmp_path, monkeypatch, deckcraft_adapter
):
    executable, adapter = deckcraft_adapter
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    prepared = prepare_deck(
        static_review_spec(tmp_path, cliPath=str(executable)), adapter
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert job["observation"]["release"] == "0.18.1"
    assert job["inputs"] == []
    assert Path(event["saved"]["locator"]).name == "component.deckcraft"
    with Image.open(event["outputs"][0]["locator"]) as image:
        assert image.info["srgb"] == 0
        assert image.size == (320, 180)
        assert image.getpixel((160, 90)) == (106, 48, 80, 255)
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["standalone"]["admission"] == "standalone-review"
    assert "midpoint of the selected fade" in review["standalone"]["losses"][0]
    assert "generatedStillRef" not in review["standalone"]


def test_native_lightcraft_recovers_isolated_treatment_from_snapshot(
    tmp_path, monkeypatch, lightcraft_adapter
):
    executable, adapter = lightcraft_adapter
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (320, 180), (65, 107, 144)).save(source, quality=100)
    original = file_fingerprint(source)
    prepared = prepare_light(
        photo_spec(tmp_path, source, cliPath=str(executable)), adapter
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert job["observation"]["release"] == "0.21.1"
    assert job["inputs"] == [original] == [file_fingerprint(source)]
    assert Path(event["saved"]["locator"]).name == "component.snap"
    with Image.open(event["outputs"][0]["locator"]) as image:
        assert image.info["icc_profile"]
        assert image.mode == "RGBA"
        assert image.getpixel((160, 90)) == (81, 132, 178, 255)
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["standalone"]["nativeLibrary"]["restoreAs"] == "catalog.snap"
    assert review["standalone"]["nativeLibrary"]["original"] == original
    assert "generatedStillRef" not in review["standalone"]


def test_native_effectcraft_reopens_mask_and_renders_exact_partial_span(
    tmp_path, monkeypatch, effectcraft_adapter
):
    executable, adapter, font = effectcraft_adapter
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    prepared = prepare_effect(
        effect_spec(
            tmp_path,
            cliPath=str(executable),
            effectFont=str(font),
            readRoots=[str(font.parent)],
        ),
        adapter,
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert job["observation"]["release"] == "0.24.1"
    assert job["inputs"] == [file_fingerprint(font)]
    assert Path(event["saved"]["locator"]).name == "component.ecproj"
    assert len(event["outputs"]) == 6
    for frame in event["outputs"]:
        with Image.open(frame["locator"]) as image:
            assert image.getpixel((10, 10)) == (0, 0, 0, 0)
            assert image.getpixel((270, 154)) == (22, 78, 99, 255)
            assert any(
                pixel == (255, 255, 255, 255) for _, pixel in image.getcolors(57600)
            )
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["standalone"]["admission"] == "standalone-review"
    assert review["standalone"]["sourceWindow"] == {
        "startFrame": 3,
        "endFrameExclusive": 9,
    }


def test_native_vectorcraft_graph_data_survives_reopen_and_revision(tmp_path):
    entry = os.environ.get("AVO_ARTCRAFT_VECTORCRAFT_TEST_CLI")
    if not entry:
        pytest.skip("Select the installed VectorCraft 0.24.1 CLI")
    executable = Path(entry).resolve(strict=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("VECTORCRAFT_")
    }
    environment["VECTORCRAFT_NO_PREFS"] = "1"

    def run(name, steps, target, *, source=None):
        script = tmp_path / f"{name}.json"
        script.write_text(json.dumps(steps), encoding="utf-8")
        initial = [] if source is None else ["--in", str(source)]
        result = subprocess.run(
            [
                str(executable),
                "--safe-mode",
                "run",
                *initial,
                "--commands",
                str(script),
                "--scale",
                "1",
                "--export",
                str(target),
            ],
            cwd=tmp_path,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=14,
        )
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        assert rows[-1]["step"] == "export"
        assert rows[-1]["result"]["path"] == str(target)
        return {row["command"]: row["result"] for row in rows if row["step"] == "cmd"}

    source = tmp_path / "chart.vectorcraft"
    original = tmp_path / "chart.png"
    data = {
        "series": ["Current", "Previous"],
        "categories": ["A", "B"],
        "rows": [[2, 5], [7, 3]],
    }
    created = run(
        "create",
        [
            _vector_step(
                "file.new",
                name="Editable data preview",
                width=320,
                height=180,
                units="Pixels",
                colorMode="rgb",
                backgroundContents="transparent",
                created=0,
            ),
            _vector_step(
                "graph.create", type="column", x=45, y=36, width=230, height=110, **data
            ),
            _vector_step("file.save", path=str(source)),
        ],
        original,
    )
    graph = created["graph.create"]["id"]
    fingerprint = file_fingerprint(source)
    inspect = [
        _vector_step("select.set", ids=[graph]),
        _vector_step("graph.setData", id=graph),
    ]
    reopened = tmp_path / "reopened.png"
    facts = run("inspect", inspect, reopened, source=source)["graph.setData"]
    assert {key: facts[key] for key in data} == data
    assert _vector_rgba(reopened) == _vector_rgba(original)
    vector = tmp_path / "chart.svg"
    run("exchange", inspect, vector, source=source)
    root = ET.parse(vector).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["viewBox"] == "0 0 320 180"
    assert len(root) > 0

    updated = {**data, "rows": [[9, 1], [4, 8]]}
    revised = tmp_path / "new-chart.vectorcraft"
    after = tmp_path / "new-chart.png"
    run(
        "revise",
        [
            inspect[0],
            _vector_step("graph.setData", id=graph, **updated),
            _vector_step("file.save", path=str(revised)),
        ],
        after,
        source=source,
    )
    changed = run(
        "check-revision", inspect, tmp_path / "new-reopened.png", source=revised
    )
    assert {key: changed["graph.setData"][key] for key in updated} == updated
    assert _vector_rgba(after) != _vector_rgba(original)

    partial = tmp_path / "partial.vectorcraft"
    missing_export = tmp_path / "partial.png"
    with pytest.raises(subprocess.CalledProcessError):
        run(
            "partial-save",
            [
                _vector_step("file.save", path=str(partial)),
                _vector_step("graph.setData", id=graph),
            ],
            missing_export,
            source=source,
        )
    assert partial.is_file()
    assert not missing_export.exists()
    partial_png = tmp_path / "partial-reopened.png"
    run("check-partial", inspect, partial_png, source=partial)
    assert _vector_rgba(partial_png) == _vector_rgba(original)
    assert file_fingerprint(source) == fingerprint


def _vector_step(command, **parameters):
    return {"command": command, "params": parameters}


def _vector_rgba(path):
    with Image.open(path) as image:
        assert image.mode == "RGBA" and image.size == (320, 180)
        return image.tobytes()
