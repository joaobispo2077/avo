"""Opt-in checks against explicitly selected local ArtCraft installations."""

import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms
from tests.test_artcraft_profiles import (
    fig_spec,
    photo_spec,
    prepare_fig,
    prepare_photo,
)

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.timeline.artcraft_stills import read_generated_still
from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration


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


def _installed_adapter(tmp_path, variable, product):
    entry = os.environ.get(variable)
    if not entry:
        pytest.skip(f"set {variable} to the installed Windows {product} CLI")
    executable = Path(entry).resolve(strict=True)

    def observe(_installed, roots):
        assert all(
            Path(root).is_relative_to(tmp_path)
            for root in roots["read"] + roots["write"]
        )
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
    prepared = prepare_fig(fig_spec(tmp_path, cliPath=str(executable)), adapter)
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
