"""Resolve reference metadata is read from bounded exports, never from its UI."""

import struct
import zipfile
import zlib

import pytest


def _drt(tmp_path, *, fusion=None, width=2560, height=1440):
    frame_rate = (struct.pack("<d", 60) + bytes(8)).hex()
    resolution = struct.pack(">qq", width, height).hex()
    extent = struct.pack("<dd", 0, 5).hex()
    media = f"<Root><ListMgt::Table/><Sm2Sequence><FrameRate>{frame_rate}</FrameRate><Resolution>{resolution}</Resolution><MediaExtents>{extent}</MediaExtents><NumOutputAudioChannels>2</NumOutputAudioChannels></Sm2Sequence></Root>"
    fusion = (
        fusion
        or '{ Template = TextPlus { Inputs = { StyledText = Input { Value = "2026", }, Font = Input { Value = "Segoe UI", }, Style = Input { Value = "Semibold", }, Size = Input { Value = 0.09, }, Width = Input { Value = 2560, }, Height = Input { Value = 1440, }, GlobalOut = Input { Value = 299, }, } } }'
    )
    inner = bytes(12) + zlib.compress(fusion.encode())
    compressed = (struct.pack(">I", len(inner)) + zlib.compress(inner)).hex()
    path = tmp_path / "timeline.drt"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("MediaPool/Master/MpFolder.xml", media)
        z.writestr(
            "SeqContainer/one.xml",
            f"<Sm2SequenceContainer><CompositionBA>{compressed}</CompositionBA></Sm2SequenceContainer>",
        )
    return path


def test_sidecar_recovers_program_settings_and_static_title_without_resolve(tmp_path):
    from avo.adapters.media.resolve_sidecar import read_resolve_sidecar

    facts = read_resolve_sidecar(_drt(tmp_path))
    assert facts["output"]["width"] == 2560 and facts["output"]["height"] == 1440
    assert facts["output"]["frameRate"] == {"num": 60, "den": 1}
    assert facts["durationSeconds"] == 5
    title = facts["titles"][0]
    assert (
        title["text"] == "2026"
        and title["fontFamily"] == "Segoe UI"
        and title["fontStyle"] == "Semibold"
    )
    assert title["normalizedSize"] == 0.09


@pytest.mark.parametrize(
    "bad", ['<!DOCTYPE r [<!ENTITY bad "x">]><r>&bad;</r>', "<broken>"]
)
def test_sidecar_rejects_entities_and_malformed_xml(tmp_path, bad):
    from avo.adapters.media.resolve_sidecar import read_resolve_sidecar

    p = tmp_path / "bad.drt"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("MediaPool/Master/MpFolder.xml", bad)
    with pytest.raises(ValueError):
        read_resolve_sidecar(p)


@pytest.mark.parametrize(
    "extra",
    [
        "Red1 = Input { Value = 0.4, },",
        "Center = Input { Value = {0.2, 0.3}, },",
        'Size = Input { Expression = "time", },',
        "Something = Blur { Inputs = {} },",
        'Danger = Input { Value = dofile("anything"), },',
    ],
)
def test_sidecar_preserves_unsupported_fusion_as_warning_instead_of_guessing(
    tmp_path, extra
):
    from avo.adapters.media.resolve_sidecar import read_resolve_sidecar

    fusion = (
        '{ Template = TextPlus { Inputs = { StyledText = Input { Value = "2026", }, Font = Input { Value = "Segoe UI", }, Style = Input { Value = "Semibold", }, Size = Input { Value = 0.09, }, Width = Input { Value = 2560, }, Height = Input { Value = 1440, }, GlobalOut = Input { Value = 299, }, '
        + extra
        + " } } }"
    )
    facts = read_resolve_sidecar(_drt(tmp_path, fusion=fusion))
    assert facts["titles"] == []
    assert facts["warnings"]


def test_sidecar_rejects_non_zip_archive(tmp_path):
    from avo.adapters.media.resolve_sidecar import read_resolve_sidecar

    path = tmp_path / "invalid.drt"
    path.write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="Malformed"):
        read_resolve_sidecar(path)
