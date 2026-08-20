"""TDD for footage-root hybrid EDITLOG (task-003). Renderer lands in task-005/006."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from avo.timeline.store import ArtifactStore
from avo.timeline.workspace import TimelineWorkspace

DIGEST_START_MARK = "<!-- avo:editlog-digest:start -->"
DIGEST_END_MARK = "<!-- avo:editlog-digest:end -->"
HUMAN_NOTES_HEADING_MARK = "## Human notes"
TIMEBASE = {"num": 1, "den": 1000}
SHA_A = "a" * 64
GENERATED_AT = "2026-08-18T13:33:00Z"
HUMAN_NOTE_BYTES = (
    b"Keep the pause after the joke.\n\n"
    b"- reviewer: vitor\n"
    b"## Picture\n"
    b"This leftover heading lives in notes, not the digest.\n"
)

INVENTED_CUT = "phantom-segment-that-json-does-not-contain"


@pytest.fixture
def editlog():
    from avo import editlog as module

    return module


def _project(raw_dir: Path) -> Path:
    path = raw_dir / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "provider": "bishop",
                "rawDir": str(raw_dir),
                "timeline": {
                    "directory": "edit/timeline",
                    "reviewDirectory": "edit/review",
                    "generatedEdlPath": "edit/edl.json",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def empty_raw_dir(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "empty-footage"
    raw_dir.mkdir(parents=True)
    _project(raw_dir)
    return raw_dir


def _time(
    ticks: int, *, domain: str = "raw-source", source_id: str | None = "camera"
) -> dict[str, object]:
    value: dict[str, object] = {
        "ticks": ticks,
        "timebase": dict(TIMEBASE),
        "domain": domain,
    }
    if domain == "raw-source" and source_id:
        value["sourceId"] = source_id
    return value


def _hybrid_text(digest_body: str, notes: str) -> str:
    return (
        "# EDITLOG\n\n"
        f"{DIGEST_START_MARK}\n"
        f"{digest_body.rstrip()}\n"
        f"{DIGEST_END_MARK}\n\n"
        f"{HUMAN_NOTES_HEADING_MARK}\n\n"
        f"{notes}"
    )


def write_hybrid(raw_dir: Path, *, digest_body: str, notes: str) -> Path:
    path = raw_dir / "EDITLOG.md"
    path.write_bytes(_hybrid_text(digest_body, notes).encode("utf-8"))
    return path


def well_formed_raw_dir(tmp_path: Path) -> Path:
    raw_dir = empty_raw_dir(tmp_path / "hybrid")
    write_hybrid(
        raw_dir,
        digest_body="_Generated: 2026-01-01T00:00:00Z_\n\n## Picture\n\nstale\n",
        notes=HUMAN_NOTE_BYTES.decode("utf-8"),
    )
    return raw_dir


def digest_less_raw_dir(tmp_path: Path) -> Path:
    raw_dir = empty_raw_dir(tmp_path / "digest-less")
    (raw_dir / "EDITLOG.md").write_text(
        "# Old notes\n\nWe cut the intro by hand before AVO wrote a digest.\n",
        encoding="utf-8",
        newline="\n",
    )
    return raw_dir


def _append(
    store: ArtifactStore,
    snapshot: dict,
    *,
    reason: str,
    diff: list[dict] | None = None,
) -> dict:
    return store.append_revision(
        snapshot=snapshot,
        actor="agent",
        reason=reason,
        diff=diff or [],
    )


def indexed_raw_dir(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "indexed-footage"
    raw_dir.mkdir(parents=True)
    project = _project(raw_dir)
    workspace = TimelineWorkspace.from_project(project, video_id="demo")
    workspace.initialize()

    cmap = workspace.store("cmap")
    _append(
        cmap,
        {
            "sources": [
                {
                    "sourceId": "camera",
                    "kind": "raw",
                    "locator": "raw/cam.mp4",
                    "fingerprint": {"sha256": SHA_A, "sizeBytes": 10},
                }
            ],
            "segments": [
                {
                    "segmentId": "keep-intro",
                    "sourceId": "camera",
                    "in": _time(0),
                    "out": _time(65000),
                    "reason": "keep promise",
                }
            ],
        },
        reason="keep intro",
        diff=[
            {
                "opId": "rm-dead-air",
                "op": "remove",
                "target": {"collection": "segments", "stableId": "dead-air"},
                "reason": "cut pause",
                "actorIntent": "tighten",
                "before": {"segmentId": "dead-air"},
            }
        ],
    )
    cmap.approve(
        cmap.load_index()["headRevisionId"],
        revision_hash=cmap.revision(cmap.load_index()["headRevisionId"])["contentHash"],
        candidate_hash=SHA_A,
    )

    _append(
        workspace.store("sync-map"),
        {
            "transform": {
                "kind": "constant-offset",
                "offsetTicks": 128,
                "timebase": dict(TIMEBASE),
            },
            "signConvention": "positive-audio-delay",
            "fullProgramValidation": {"status": "pass", "maxResidualTicks": 4},
        },
        reason="calibrated offset",
    )

    _append(
        workspace.store("bmap"),
        {
            "cues": [
                {
                    "cueId": "music-bed",
                    "start": _time(1000, domain="cmap-output", source_id=None),
                    "end": _time(4000, domain="cmap-output", source_id=None),
                    "kind": "music",
                    "reason": "underscore dialogue",
                    "intent": "support",
                    "targetLayerId": "music",
                },
                {
                    "cueId": "lower-third",
                    "start": _time(2000, domain="cmap-output", source_id=None),
                    "end": _time(5000, domain="cmap-output", source_id=None),
                    "kind": "animation",
                    "reason": "name card",
                    "intent": "identify",
                    "targetLayerId": "graphics",
                },
            ]
        },
        reason="audio and motion cues",
    )

    _append(
        workspace.store("tracks"),
        {
            "audioTracks": {
                "layers": [
                    {
                        "layerId": "dialogue",
                        "order": 0,
                        "role": "dialogue",
                        "gainDb": 0,
                        "mute": False,
                    }
                ]
            },
            "videoTracks": {"layers": []},
        },
        reason="dialogue lead",
    )

    _append(
        workspace.store("animation"),
        {
            "strategy": {
                "formatDiagnosis": {
                    "format": "talking-head-review",
                    "viewerIntent": "decide",
                    "motionDensity": 2,
                },
                "density": 2,
                "framework": "hyperframes",
                "components": [{"componentId": "chapter-pair"}],
            }
        },
        reason="motion strategy",
    )

    review_dir = workspace.review_dir / "cut-proof"
    review_dir.mkdir(parents=True)
    (review_dir / "review.json").write_text(
        json.dumps(
            {
                "state": "needs-human-judgment",
                "checkpoint": "cut-proof",
                "reviewer": "creator",
                "updatedAt": GENERATED_AT,
                "unresolvedRisks": [
                    {
                        "classification": "blocker",
                        "message": "sync drift at the join",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (review_dir / "approval-gate.md").write_text(
        "# Approval gate\n\nAI state: needs-human-judgment\n\n"
        "## Unresolved risks\n\n- blocker: sync drift at the join\n",
        encoding="utf-8",
        newline="\n",
    )

    masters = raw_dir / "edit" / "masters"
    masters.mkdir(parents=True)
    (masters / "20260818-demo-fine-cut-v001.mp4").write_bytes(b"master")
    (masters / "final-final.mp4").write_bytes(b"bad-name")
    return raw_dir


def notes_region_bytes(path: Path) -> bytes:
    text = path.read_bytes()
    heading = HUMAN_NOTES_HEADING_MARK.encode("utf-8")
    index = text.find(heading)
    assert index != -1, "Human notes heading missing"
    return text[index:]


def strip_generated(digest: str) -> str:
    return re.sub(r"_Generated:[^\n]*\n?", "", digest)


def digest_region(text: str) -> str:
    start = text.index(DIGEST_START_MARK)
    end = text.index(DIGEST_END_MARK) + len(DIGEST_END_MARK)
    return text[start:end]


def _conflict_error(editlog, raw_dir: Path):
    try:
        result = editlog.refresh_editlog(raw_dir)
    except editlog.EditlogError as exc:
        return exc
    assert result["ok"] is False
    assert result["code"] == "AVO-EL-001"
    return result


def test_marker_constants_match_locked_plan(editlog) -> None:
    assert editlog.DIGEST_START == DIGEST_START_MARK
    assert editlog.DIGEST_END == DIGEST_END_MARK
    assert editlog.HUMAN_NOTES_HEADING == HUMAN_NOTES_HEADING_MARK
    assert editlog.RECENT_EVENTS_CAP == 20


def test_refresh_writes_footage_root_not_edit_copy(editlog, tmp_path: Path) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    assert Path(result["path"]).resolve() == (raw_dir / "EDITLOG.md").resolve()
    assert (raw_dir / "EDITLOG.md").is_file()
    assert not (raw_dir / "edit" / "EDITLOG.md").exists()


def test_first_run_creates_template_with_markers_and_notes_heading(
    editlog, tmp_path: Path
) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    assert result["created"] is True
    text = (raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert DIGEST_START_MARK in text
    assert DIGEST_END_MARK in text
    assert text.index(DIGEST_START_MARK) < text.index(DIGEST_END_MARK)
    assert HUMAN_NOTES_HEADING_MARK in text
    assert text.index(DIGEST_END_MARK) < text.index(HUMAN_NOTES_HEADING_MARK)
    for heading in ("## Picture", "## Audio", "## Motion", "## Approvals"):
        assert heading in digest_region(text)


def test_refresh_replaces_digest_only_and_notes_are_byte_identical(
    editlog, tmp_path: Path
) -> None:
    raw_dir = well_formed_raw_dir(tmp_path)
    path = raw_dir / "EDITLOG.md"
    before_notes = notes_region_bytes(path)
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    after = path.read_bytes()
    assert notes_region_bytes(path) == before_notes
    assert HUMAN_NOTE_BYTES in after
    digest = digest_region(after.decode("utf-8"))
    assert "stale" not in digest


def test_digest_less_root_becomes_human_notes(editlog, tmp_path: Path) -> None:
    raw_dir = digest_less_raw_dir(tmp_path)
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    text = (raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert DIGEST_START_MARK in text
    notes = notes_region_bytes(raw_dir / "EDITLOG.md").decode("utf-8")
    assert "We cut the intro by hand before AVO wrote a digest." in notes


@pytest.mark.parametrize(
    "body",
    [
        (
            f"# EDITLOG\n\n{DIGEST_START_MARK}\npartial digest\n\n"
            f"{HUMAN_NOTES_HEADING_MARK}\n\nkeep me\n"
        ),
        _hybrid_text("body", "keep me\n")
        + f"\n{DIGEST_START_MARK}\nextra\n{DIGEST_END_MARK}\n",
        (
            f"{DIGEST_START_MARK}\nouter\n{DIGEST_START_MARK}\ninner\n"
            f"{DIGEST_END_MARK}\n{DIGEST_END_MARK}\n\n"
            f"{HUMAN_NOTES_HEADING_MARK}\n\nkeep me\n"
        ),
        (
            f"{DIGEST_END_MARK}\nbackwards\n{DIGEST_START_MARK}\n\n"
            f"{HUMAN_NOTES_HEADING_MARK}\n\nkeep me\n"
        ),
    ],
    ids=["missing-end", "duplicate", "nested", "start-after-end"],
)
def test_marker_conflict_is_fail_closed_avo_el_001(
    editlog, tmp_path: Path, body: str
) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    path = raw_dir / "EDITLOG.md"
    original = body.encode("utf-8")
    path.write_bytes(original)
    conflict = _conflict_error(editlog, raw_dir)
    code = getattr(conflict, "code", None) or conflict["code"]
    assert code == "AVO-EL-001"
    assert path.read_bytes() == original


def test_missing_indexes_use_placeholders_and_do_not_invent_cuts(
    editlog, tmp_path: Path
) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    digest = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    assert "## Picture" in digest
    assert "## Audio" in digest
    assert "## Motion" in digest
    assert "## Approvals" in digest
    assert "Picture: not yet authored" in digest
    assert "Audio: not yet authored" in digest
    assert "Motion: not yet authored" in digest
    assert INVENTED_CUT not in digest
    assert "keep-intro" not in digest
    assert "## Sync" not in digest


def test_format_clock_uses_human_mmss_and_hmmss(editlog) -> None:
    assert editlog.format_clock(0, TIMEBASE) == "00:00"
    assert editlog.format_clock(65000, TIMEBASE) == "01:05"
    assert editlog.format_clock(3723000, TIMEBASE) == "1:02:03"


def test_render_digest_uses_human_clocks_not_ticks_only(
    editlog, tmp_path: Path
) -> None:
    raw_dir = indexed_raw_dir(tmp_path)
    digest = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    assert "01:05" in digest
    picture = digest[digest.index("## Picture") : digest.index("## Audio")]
    assert re.search(r"\b65000\b", picture) is None or "01:05" in picture
    assert "ticks-only" not in picture


def test_render_digest_is_deterministic_aside_from_generated_at(
    editlog, tmp_path: Path
) -> None:
    raw_dir = indexed_raw_dir(tmp_path)
    first = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    second = editlog.render_digest(raw_dir, generated_at="2026-08-18T14:00:00Z")
    assert first != second
    assert strip_generated(first) == strip_generated(second)
    third = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    assert third == first


def test_picture_audio_motion_from_indexes_fold_sync_without_sync_heading(
    editlog, tmp_path: Path
) -> None:
    raw_dir = indexed_raw_dir(tmp_path)
    digest = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    assert "keep-intro" in digest or "keep promise" in digest
    assert "dead-air" in digest or "cut pause" in digest
    assert "dialogue" in digest
    assert "music-bed" in digest or "underscore dialogue" in digest
    assert "chapter-pair" in digest or "hyperframes" in digest
    assert "lower-third" in digest or "name card" in digest
    assert "## Sync" not in digest
    assert "offset" in digest.lower() or "128" in digest
    assert INVENTED_CUT not in digest


def test_approvals_from_events_review_and_immutable_export_names(
    editlog, tmp_path: Path
) -> None:
    raw_dir = indexed_raw_dir(tmp_path)
    digest = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    approvals = digest[digest.index("## Approvals") :]
    assert "cut-proof" in approvals or "needs-human-judgment" in approvals
    assert "creator" in approvals or "sync drift" in approvals
    assert "20260818-demo-fine-cut-v001" in approvals
    assert "final-final" not in approvals
    assert "final2" not in approvals


def test_refresh_succeeds_without_sibling_audio_animation_editlogs(
    editlog, tmp_path: Path
) -> None:
    raw_dir = indexed_raw_dir(tmp_path)
    assert not (raw_dir / "AUDIO-EDITLOG.md").exists()
    assert not (raw_dir / "ANIMATION-EDITLOG.md").exists()
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    text = (raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert "## Audio" in digest_region(text)
    assert "## Motion" in digest_region(text)


def test_recent_events_cap_is_20_newest_first(editlog, tmp_path: Path) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    workspace = TimelineWorkspace.from_project(
        raw_dir / "avo.project.json", video_id="events"
    )
    workspace.initialize()
    store = workspace.store("cmap")
    revision = _append(store, {"segments": []}, reason="seed")
    for index in range(25):
        store.record_decision(
            decision="approved",
            revision_id=revision["revisionId"],
            revision_hash=revision["contentHash"],
            candidate_hash=SHA_A,
            dependency_hashes={"revision": revision["contentHash"]},
            actor="creator",
            checkpoint="cut-proof",
            scope="exact-candidate",
            reason=f"approval-wave-{index:02d}",
            evidence_bundle_hash=SHA_A,
            decided_at=f"2026-08-18T00:{index:02d}:00Z",
        )
    digest = editlog.render_digest(raw_dir, generated_at=GENERATED_AT)
    approvals = digest[digest.index("## Approvals") :]
    assert approvals.index("approval-wave-24") < approvals.index("approval-wave-05")
    assert "approval-wave-04" not in approvals
    assert "approval-wave-00" not in approvals
    assert len(re.findall(r"approval-wave-\d+", approvals)) == 20


def test_refresh_does_not_mutate_canonical_indexes(editlog, tmp_path: Path) -> None:
    raw_dir = indexed_raw_dir(tmp_path)
    timeline = raw_dir / "edit" / "timeline"
    names = (
        "cmap.json",
        "bmap.json",
        "tracks.json",
        "animation.json",
        "sync-map.json",
    )
    before = {name: (timeline / name).read_bytes() for name in names}
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    for name, payload in before.items():
        assert (timeline / name).read_bytes() == payload
    assert (raw_dir / "EDITLOG.md").is_file()
    assert not (raw_dir / "edit" / "EDITLOG.md").exists()


def test_template_text_matches_shipped_markers_and_headings(editlog) -> None:
    repo = Path(__file__).resolve().parents[1]
    shipped = (repo / "docs" / "templates" / "logs" / "EDITLOG.md").read_text(
        encoding="utf-8"
    )
    generated = editlog.template_text()
    for needle in (
        DIGEST_START_MARK,
        DIGEST_END_MARK,
        HUMAN_NOTES_HEADING_MARK,
        "## Picture",
        "## Audio",
        "## Motion",
        "## Approvals",
        "Picture: not yet authored",
    ):
        assert needle in shipped
        assert needle in generated
    assert shipped.index(DIGEST_END_MARK) < shipped.index(HUMAN_NOTES_HEADING_MARK)


def test_after_canonical_write_never_raises(
    editlog, tmp_path: Path, monkeypatch
) -> None:
    raw_dir = empty_raw_dir(tmp_path)

    def boom(_raw_dir, **_kwargs):
        raise RuntimeError("digest boom")

    monkeypatch.setattr(editlog, "refresh_editlog", boom)
    result = editlog.after_canonical_write(raw_dir)
    assert result["ok"] is False
    assert result["code"] == "AVO-EL-HOOK"


def test_unreadable_index_is_avo_el_003_and_leaves_file(
    editlog, tmp_path: Path
) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    first = editlog.refresh_editlog(raw_dir)
    assert first["ok"] is True
    path = raw_dir / "EDITLOG.md"
    original = path.read_bytes()
    timeline = raw_dir / "edit" / "timeline"
    timeline.mkdir(parents=True)
    (timeline / "cmap.json").write_text("{not-json", encoding="utf-8")
    try:
        editlog.refresh_editlog(raw_dir)
        raise AssertionError("expected AVO-EL-003")
    except editlog.EditlogError as exc:
        assert exc.code == "AVO-EL-003"
    assert path.read_bytes() == original


def test_edit_only_copy_migrates_into_human_notes(editlog, tmp_path: Path) -> None:
    raw_dir = empty_raw_dir(tmp_path)
    edit_copy = raw_dir / "edit" / "EDITLOG.md"
    edit_copy.parent.mkdir(parents=True, exist_ok=True)
    body = "Legacy cut notes lived under edit/.\n"
    edit_copy.write_text(body, encoding="utf-8", newline="\n")
    result = editlog.refresh_editlog(raw_dir)
    assert result["ok"] is True
    assert result["migratedEditCopy"] is True
    root = (raw_dir / "EDITLOG.md").read_text(encoding="utf-8")
    assert DIGEST_START_MARK in root
    notes = notes_region_bytes(raw_dir / "EDITLOG.md").decode("utf-8")
    assert "### Migrated from edit/EDITLOG.md" in notes
    assert "Legacy cut notes lived under edit/" in notes
    assert edit_copy.is_file()


def test_both_present_appends_edit_copy_once(editlog, tmp_path: Path) -> None:
    raw_dir = well_formed_raw_dir(tmp_path)
    edit_copy = raw_dir / "edit" / "EDITLOG.md"
    edit_copy.parent.mkdir(parents=True, exist_ok=True)
    extra = "Imported from the edit/ copy.\n"
    edit_copy.write_text(extra, encoding="utf-8", newline="\n")
    first = editlog.refresh_editlog(raw_dir)
    assert first["migratedEditCopy"] is True
    notes_once = notes_region_bytes(raw_dir / "EDITLOG.md")
    assert extra.encode("utf-8") in notes_once
    second = editlog.refresh_editlog(raw_dir)
    assert second["migratedEditCopy"] is False
    assert notes_region_bytes(raw_dir / "EDITLOG.md") == notes_once


def test_cli_refresh_project_and_raw_dir(editlog, tmp_path: Path, capsys) -> None:
    from avo.cli import main

    raw_dir = empty_raw_dir(tmp_path)
    project = raw_dir / "avo.project.json"
    code = main(["editlog", "refresh", "--project", str(project), "--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert Path(payload["path"]).resolve() == (raw_dir / "EDITLOG.md").resolve()

    raw_only = empty_raw_dir(tmp_path / "raw-only")
    code = main(["editlog", "refresh", "--raw-dir", str(raw_only), "--json"])
    assert code == 0
    assert (raw_only / "EDITLOG.md").is_file()


def test_cli_mismatch_and_marker_conflict_fail_closed(
    editlog, tmp_path: Path, capsys
) -> None:
    from avo.cli import main

    raw_dir = well_formed_raw_dir(tmp_path)
    other = tmp_path / "other-footage"
    other.mkdir()
    code = main(
        [
            "editlog",
            "refresh",
            "--project",
            str(raw_dir / "avo.project.json"),
            "--raw-dir",
            str(other),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code != 0
    payload = json.loads(captured.out)
    assert payload["code"] == "AVO-EL-002"

    original = (raw_dir / "EDITLOG.md").read_bytes()
    (raw_dir / "EDITLOG.md").write_bytes(
        (f"{DIGEST_START_MARK}\npartial\n{HUMAN_NOTES_HEADING_MARK}\nkeep\n").encode()
    )
    original = (raw_dir / "EDITLOG.md").read_bytes()
    code = main(
        [
            "editlog",
            "refresh",
            "--project",
            str(raw_dir / "avo.project.json"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code != 0
    payload = json.loads(captured.out)
    assert payload["code"] == "AVO-EL-001"
    assert (raw_dir / "EDITLOG.md").read_bytes() == original


def test_cli_does_not_mutate_indexes(editlog, tmp_path: Path) -> None:
    from avo.cli import main

    raw_dir = indexed_raw_dir(tmp_path)
    timeline = raw_dir / "edit" / "timeline"
    before = (timeline / "cmap.json").read_bytes()
    code = main(
        [
            "editlog",
            "refresh",
            "--project",
            str(raw_dir / "avo.project.json"),
            "--json",
        ]
    )
    assert code == 0
    assert (timeline / "cmap.json").read_bytes() == before
