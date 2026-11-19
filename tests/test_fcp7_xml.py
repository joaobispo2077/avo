"""The xmeml reader bounds untrusted documents and keeps exact clocks and ownership."""

from fractions import Fraction

import pytest

from avo.adapters.media.fcp7_xml import Fcp7Error, parse_fcp7_xml, write_fcp7_xml


def document(path_url):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="5"><sequence id="seq-one">
  <name>Example sequence</name><duration>48</duration>
  <rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
  <timecode><frame>108000</frame></timecode>
  <media><video><track><enabled>TRUE</enabled>
    <clipitem id="take-first"><start>0</start><end>12</end><in>2</in><out>14</out>
      <file id="source-one"><pathurl>{path_url}</pathurl><duration>240</duration>
        <rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate><timecode><frame>1800</frame></timecode>
      </file><filter><effect><name>External finishing</name></effect></filter>
    </clipitem>
    <clipitem id="take-again"><start>24</start><end>36</end><in>22</in><out>34</out><file id="source-one" /></clipitem>
  </track></video><audio><track><enabled>TRUE</enabled>
    <clipitem id="audio-first"><start>0</start><end>12</end><in>2</in><out>14</out><file id="source-one" />
      <sourcetrack><mediatype>audio</mediatype><trackindex>2</trackindex></sourcetrack>
    </clipitem>
  </track></audio></media>
</sequence></xmeml>"""


def test_bom_rate_origins_tracks_and_repeated_local_source(tmp_path):
    source = tmp_path / "criança footage.mov"
    parsed = parse_fcp7_xml(
        document(source.as_uri()).encode("utf-8-sig"), roots=[tmp_path]
    )
    assert parsed["rate"] == Fraction(30_000, 1001)
    assert parsed["originFrame"] == 108_000
    source_fact = parsed["sources"]["source-one"]
    assert source_fact["locator"] == source
    assert source_fact["originFrame"] == 1800
    video, audio = parsed["tracks"]
    assert [(row["id"], row["start"], row["in"]) for row in video["clips"]] == [
        ("take-first", 0, 2),
        ("take-again", 24, 22),
    ]
    assert audio["clips"][0]["sourceTrack"] == 2
    assert parsed["unknown"]["filter"] == 1
    assert video["clips"][0]["unknown"]["filter"] == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda row: row.replace('encoding="UTF-8"', 'encoding="UTF-16"'),
        lambda row: row.replace(
            "<!DOCTYPE xmeml>", '<!DOCTYPE xmeml SYSTEM "unapproved.dtd">'
        ),
        lambda row: row.replace(
            "<!DOCTYPE xmeml>", '<!DOCTYPE xmeml [<!ENTITY example "placeholder">]>'
        ),
        lambda row: row.replace(
            "<name>Example sequence</name>",
            '<x:include xmlns:x="http://www.w3.org/2001/XInclude" href="unapproved.xml"/>',
        ),
        lambda row: row.replace(
            "<name>Example sequence</name>", "<outer>" * 64 + "</outer>" * 64
        ),
    ],
)
def test_rejects_unqualified_markup_and_depth_before_inspection(tmp_path, change):
    source = tmp_path / "original.mov"
    with pytest.raises(Fcp7Error):
        parse_fcp7_xml(change(document(source.as_uri())).encode(), roots=[tmp_path])


def test_root_and_explicit_local_relink_are_distinct(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    old = (tmp_path / "old" / "file.mov").as_uri()
    with pytest.raises(Fcp7Error, match="outside"):
        parse_fcp7_xml(document(old).encode(), roots=[root])
    result = parse_fcp7_xml(
        document(old).encode(), roots=[root], relink={old: root / "current.mov"}
    )
    assert result["sources"]["source-one"]["locator"] == root / "current.mov"
    former_volume = "file://localhost/Volumes/Archive/file.mov"
    relocated = parse_fcp7_xml(
        document(former_volume).encode(),
        roots=[root],
        relink={former_volume: root / "current.mov"},
    )
    assert relocated["sources"]["source-one"]["locator"] == root / "current.mov"
    remote = "file://unapproved.example/path/file.mov"
    with pytest.raises(Fcp7Error, match="local"):
        parse_fcp7_xml(
            document(remote).encode(),
            roots=[root],
            relink={remote: root / "current.mov"},
        )


def test_known_ranges_channels_markers_and_gaps_round_trip(tmp_path):
    source = tmp_path / "original.mov"
    xml = document(source.as_uri())
    unknown = parse_fcp7_xml(xml.encode(), roots=[tmp_path])
    with pytest.raises(Fcp7Error, match="External finishing"):
        write_fcp7_xml(unknown)
    clean = xml.replace(
        "<filter><effect><name>External finishing</name></effect></filter>", ""
    )
    parsed = parse_fcp7_xml(clean.encode(), roots=[tmp_path])
    parsed["tracks"][1].update(enabled=False, outputChannel=1)
    parsed["markers"].append(
        {"name": "Review & timing", "comment": "Keep <word>", "in": 6, "out": -1}
    )
    assert parse_fcp7_xml(write_fcp7_xml(parsed), roots=[tmp_path]) == parsed
    parsed["tracks"][0]["clips"][0]["start"] = Fraction(1, 2)
    with pytest.raises(Fcp7Error, match="integer frames"):
        write_fcp7_xml(parsed)


@pytest.mark.parametrize(
    ("bound", "limit"),
    [("MAX_BYTES", 40), ("MAX_ELEMENTS", 12), ("MAX_OCCURRENCES", 2)],
)
def test_reader_stops_at_each_declared_budget(tmp_path, monkeypatch, bound, limit):
    from avo.adapters.media import fcp7_xml

    monkeypatch.setattr(fcp7_xml, bound, limit)
    with pytest.raises(Fcp7Error, match="budget"):
        parse_fcp7_xml(
            document((tmp_path / "clip.mov").as_uri()).encode(), roots=[tmp_path]
        )
