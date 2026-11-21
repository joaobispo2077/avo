"""The initial AniCraft profile has a deterministic recipe and verified alpha."""

import pytest
from PIL import Image

from avo.artcraft import ArtCraftError
from tests.artcraft_fixtures import picture_output


def _contract(**overrides):
    return picture_output(
        **{
            "width": 640,
            "height": 360,
            "frameCount": 24,
            "frameRate": {"numerator": 24, "denominator": 1},
            **overrides,
        }
    )


def test_lower_third_has_native_text_symbol_and_exact_phase_frames(tmp_path):
    from avo.adapters.artcraft_anicraft import lower_third_steps

    source = tmp_path / "native.anicraft"
    sequence = tmp_path / "white"
    steps = lower_third_steps(
        _contract(),
        {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        source,
        sequence,
    )
    by_name = {}
    for step in steps:
        by_name.setdefault(step["cmd"], []).append(step["params"])
    assert by_name["timeline.create_tween"] == [{"frame": 3}, {"frame": 18}]
    assert by_name["timeline.insert_blank_keyframe"] == [{"frame": 3}, {"frame": 23}]
    assert by_name["text.create"][0]["text"] == "Clara Caf\u00e9"
    assert by_name["modify.convert_to_symbol"][0]["kind"] == "graphic"
    assert steps[-2] == {"cmd": "file.save_as", "params": {"path": str(source)}}
    assert steps[-1] == {
        "cmd": "file.export_png_sequence",
        "params": {"dir": str(sequence), "from": 0, "to": 23},
    }


def test_lower_third_adds_a_distinct_optional_native_secondary_line(tmp_path):
    from avo.adapters.artcraft_anicraft import lower_third_steps

    steps = lower_third_steps(
        _contract(),
        {"primaryText": "Clara", "secondaryText": "Producer", "font": "Arial"},
        tmp_path / "native.anicraft",
        tmp_path / "white",
    )
    primary, secondary = (
        step["params"] for step in steps if step["cmd"] == "text.create"
    )
    assert (primary["text"], secondary["text"]) == ("Clara", "Producer")
    assert primary["font"] == secondary["font"] == "Arial"
    assert primary["y"] < secondary["y"] and primary["size"] > secondary["size"]


def test_lower_third_can_hold_at_a_fixed_position_without_tweens(tmp_path):
    from avo.adapters.artcraft_anicraft import lower_third_steps

    steps = lower_third_steps(
        _contract(),
        {"primaryText": "Clara", "font": "Arial", "motion": "hold"},
        tmp_path / "native.anicraft",
        tmp_path / "white",
    )
    commands = {step["cmd"] for step in steps}
    assert "timeline.create_tween" not in commands
    assert "timeline.insert_keyframe" not in commands
    assert [
        step["params"]["frame"]
        for step in steps
        if step["cmd"] == "timeline.insert_blank_keyframe"
    ] == [3, 23]
    plate = next(step["params"] for step in steps if step["cmd"] == "draw.rect")
    assert plate["x"] == 48


def test_lower_third_rejects_blank_or_multiline_secondary_text(tmp_path):
    from avo.adapters.artcraft_anicraft import lower_third_steps

    for secondary in (" ", "Two\nlines"):
        with pytest.raises(ArtCraftError, match="secondary"):
            lower_third_steps(
                _contract(),
                {"primaryText": "Clara", "secondaryText": secondary, "font": "Arial"},
                tmp_path / "native.anicraft",
                tmp_path / "white",
            )


@pytest.mark.parametrize(
    "contract",
    [
        _contract(frameRate={"numerator": 24000, "denominator": 1001}),
        _contract(frameCount=9),
        _contract(width=641),
        _contract(alpha="none"),
    ],
)
def test_profile_refuses_unqualified_clocks_geometry_and_alpha(contract, tmp_path):
    from avo.adapters.artcraft_anicraft import lower_third_steps

    with pytest.raises(ArtCraftError, match="AniCraft lower-third contract"):
        lower_third_steps(
            contract,
            {"primaryText": "Name", "font": "Arial"},
            tmp_path / "native.anicraft",
            tmp_path / "frames",
        )
    assert list(tmp_path.iterdir()) == []


def _backed(pixels, background):
    image = Image.new("RGB", (len(pixels), 1))
    image.putdata(
        [
            tuple(
                (component * alpha + base * (255 - alpha) + 127) // 255
                for component, base in zip(rgb, background, strict=True)
            )
            for *rgb, alpha in pixels
        ]
    )
    return image


def test_matte_recovers_opaque_edges_and_clear_pixels_and_verifies_third_backing():
    from avo.adapters.artcraft_anicraft import recover_matte

    pixels = [(0, 0, 0, 0), (48, 112, 204, 128), (40, 120, 200, 255)]
    white = _backed(pixels, (255, 255, 255))
    black = _backed(pixels, (0, 0, 0))
    third = _backed(pixels, (55, 113, 174))
    matte, max_error = recover_matte(white, black, third)
    assert matte.mode == "RGBA"
    assert matte.getpixel((0, 0)) == (0, 0, 0, 0)
    assert matte.getpixel((1, 0)) == (48, 112, 203, 128)
    assert matte.getpixel((2, 0)) == (40, 120, 200, 255)
    assert max_error <= 1
    third.putpixel((1, 0), (0, 0, 0))
    with pytest.raises(ArtCraftError, match="independent backing"):
        recover_matte(white, black, third)


def test_unknown_installed_font_blocks_before_the_native_authoring_batch(tmp_path):
    from avo.adapters.artcraft_anicraft import run_lower_third

    calls = []

    def invoke(directory, *args, timeout):
        calls.append(args[0])
        if args[0] == "new":
            return b""
        if args[0] == "exec":
            assert args[-1] == "text.fonts"
            return b'{"default":"Arial","families":["Arial"]}'
        pytest.fail("the selected unavailable font cannot enter native authoring")

    with pytest.raises(ArtCraftError, match="font"):
        run_lower_third(
            _contract(),
            {"primaryText": "Name", "font": "Unavailable family"},
            directory=tmp_path / "new-job",
            budget={"seconds": 60, "files": 128, "bytes": 16_000_000},
            invoke=invoke,
        )
    assert calls == ["new", "exec"]


def test_command_evidence_binds_only_the_current_lower_third_surface(tmp_path):
    from avo.adapters.artcraft_anicraft import lower_third_steps, observe_command_schema

    steps = lower_third_steps(
        _contract(),
        {"primaryText": "Name", "font": "Arial"},
        tmp_path / "component.anicraft",
        tmp_path / "white",
    )
    expected = {step["cmd"] for step in steps} | {"doc.set_stage", "text.fonts"}
    commands = [{"id": name, "params": "{}"} for name in sorted(expected)]
    first = observe_command_schema(commands)
    assert set(first) == expected
    assert (
        observe_command_schema([*commands, {"id": "file.open", "params": "{path}"}])
        == first
    )
    with pytest.raises(ArtCraftError, match="required lower-third commands"):
        observe_command_schema(
            [row for row in commands if row["id"] != "modify.convert_to_symbol"]
        )
    with pytest.raises(ArtCraftError, match="command registry"):
        observe_command_schema([*commands, commands[0]])
