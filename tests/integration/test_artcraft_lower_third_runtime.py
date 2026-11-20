"""Opt-in Windows AniCraft evidence using the user's installed release."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from tests.artcraft_fixtures import picture_output, request

from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration


def _job_contract():
    return picture_output(
        width=640,
        height=360,
        frameCount=24,
        frameRate={"numerator": 24, "denominator": 1},
    )


def _busy_background():
    canvas = Image.new("RGBA", (640, 360), "#17334f")
    draw = ImageDraw.Draw(canvas)
    for column in range(0, 640, 30):
        for row in range(0, 360, 30):
            if (column + row) % 60:
                draw.rectangle((column, row, column + 29, row + 29), fill="#f2cd78")
    return canvas


def test_installed_anicraft_saves_reopens_and_reconstructs_a_transparent_label(
    tmp_path,
):
    from avo.adapters.artcraft_anicraft import run_lower_third

    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip(
            "set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed AniCraft 0.2.1 CLI"
        )
    cli = Path(entry).resolve(strict=True)
    assert cli.is_file()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("ANICRAFT_")
    }

    def invoke(directory, *argv, timeout=5):
        result = subprocess.run(
            [str(cli), *map(str, argv)],
            capture_output=True,
            check=True,
            env=environment,
            timeout=timeout,
            cwd=directory,
        )
        return result.stdout

    assert invoke(tmp_path, "--version").strip() == b"anicraft-cli 0.2.1"
    output = _job_contract()
    budget = {"seconds": 60, "files": 128, "bytes": 16_000_000}
    first_dir = tmp_path / "first"
    result = run_lower_third(
        output,
        {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        directory=first_dir,
        budget=budget,
        invoke=invoke,
    )
    assert result["freshSessionDecodedRgbaMatched"]
    assert result["maxMatteError"] <= 1
    assert len(result["frames"]) == 24
    assert result["layers"] == ["Speaker label", "Layer 1"]
    native = Path(result["nativeSource"]["locator"])
    original = file_fingerprint(native)
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source

    source = inspect_lower_third_source(
        native,
        output,
        {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        max_bytes=budget["bytes"],
    )
    assert source["fingerprint"] == original
    assert source["editableText"] == "Clara Caf\u00e9"
    assert source["fontFamily"] == "Arial"
    tampered = tmp_path / "external-reference.anicraft"
    document = json.loads(native.read_bytes())
    document["paths"][0] = "file:///outside/native-input.svg"
    tampered.write_text(json.dumps(document), encoding="utf-8")
    from avo.artcraft import ArtCraftError

    with pytest.raises(ArtCraftError, match="vector paths"):
        inspect_lower_third_source(
            tampered,
            output,
            {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
            max_bytes=budget["bytes"],
        )

    with Image.open(result["frames"][0]["locator"]) as beginning:
        assert beginning.getchannel("A").getextrema() == (0, 0)
    with Image.open(result["frames"][8]["locator"]) as hold:
        assert hold.getchannel("A").getbbox() == (47, 267, 319, 325)
        for background in (
            Image.new("RGBA", hold.size, "white"),
            Image.new("RGBA", hold.size, "black"),
            _busy_background(),
        ):
            composite = Image.alpha_composite(background, hold)
            assert composite.getpixel((0, 0)) == background.getpixel((0, 0))
            assert composite.getpixel((60, 285)) == (16, 44, 72, 255)

    next_result = run_lower_third(
        output,
        {"primaryText": "Mar\u00eda", "font": "Arial"},
        directory=tmp_path / "second",
        budget=budget,
        invoke=invoke,
    )
    assert file_fingerprint(native) == original
    assert next_result["nativeSource"]["locator"] != str(native)
    assert next_result["frames"][8]["sha256"] != result["frames"][8]["sha256"]


def test_installed_anicraft_guided_job_round_trips_through_avo_commands(
    tmp_path, monkeypatch
):
    from avo import init_project
    from avo.mcp.bridge import run_cli

    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip(
            "set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed AniCraft 0.2.1 CLI"
        )
    cli = Path(entry).resolve(strict=True)
    application = cli.with_name("anicraft.exe")
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    spec = {
        "version": 1,
        "jobId": "guided-trial",
        "provider": "neutral-channel",
        "workspace": str(tmp_path),
        "mode": "guided",
        "document": {"state": "empty"},
        "readRoots": [],
        "authoringParameters": {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        "output": _job_contract(),
        "budget": {"files": 128, "bytes": 16_000_000, "seconds": 60},
    }
    result = run_cli(
        [
            "artcraft",
            "prepare",
            "--request-json",
            json.dumps(request()),
            "--job-spec-json",
            json.dumps(spec),
            "--provider",
            "neutral-channel",
            "--workspace",
            str(tmp_path),
            "--app",
            "anicraft",
            "--operation",
            "lower-third",
            "--mode",
            "guided",
            "--cli",
            str(cli),
            "--application",
            str(application),
            "--json",
        ]
    )
    assert result.ok, result.stderr
    prepared = result.parsed_json
    plan = run_cli(
        [
            "artcraft",
            "run",
            "--job",
            prepared["jobRef"],
            "--expected-head",
            prepared["head"],
            "--json",
        ]
    )
    assert plan.ok, plan.stderr
    handoff_ref = Path(plan.parsed_json["handoff"]["locator"])
    handoff = json.loads(handoff_ref.read_text(encoding="utf-8"))
    assert handoff["artifactState"] == "reference-only"
    assert not Path(handoff["nativeDocument"]).exists()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("ANICRAFT_")
    }
    for command in handoff["commands"]:
        assert command[0] == str(cli)
        subprocess.run(
            command,
            cwd=handoff_ref.parent,
            capture_output=True,
            timeout=10,
            check=True,
            env=environment,
        )
    inspected = run_cli(
        [
            "artcraft",
            "inspect",
            "--job",
            prepared["jobRef"],
            "--expected-head",
            plan.parsed_json["head"],
            "--json",
        ]
    )
    assert inspected.ok, inspected.stderr
    assert inspected.parsed_json["checks"]["nativeDocument"] == "returned-unverified"
    assert (
        inspected.parsed_json["sourceObservations"]["editableText"] == "Clara Caf\u00e9"
    )
    assert inspected.parsed_json["sourceObservations"]["fontFamily"] == "Arial"
    assert len(list((handoff_ref.parent / "white").glob("*.png"))) == 24
