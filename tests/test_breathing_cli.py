import json

import numpy as np
import pytest

from avo.breath_control import BreathControlError
from avo.breathing import _word_clock, build_parser, remap_raw_words, run
from avo.timeline.contracts import ContractError, file_fingerprint, validate_document


def _fixture(tmp_path, monkeypatch):
    project = tmp_path / "avo.project.json"
    project.write_text(json.dumps({"rawDir": str(tmp_path)}), encoding="utf-8")
    source = tmp_path / "dialogue.flac"
    source.write_bytes(b"test source")
    transcript = tmp_path / "words.json"
    transcript.write_text(
        json.dumps({"words": [{"text": "voz", "start": 0, "end": 0.2}]}),
        encoding="utf-8",
    )
    control = {
        "enabled": True,
        "sampleRate": 48000,
        "sourceSha256": file_fingerprint(source)["sha256"],
        "transcriptSha256": file_fingerprint(transcript)["sha256"],
        "protectedRanges": [],
        "events": [
            {
                "eventId": "breath-1",
                "startSample": 24000,
                "endSampleExclusive": 38400,
                "status": "confirmed",
                "breathRmsDb": -20,
                "speechRmsDb": -10,
            }
        ],
    }
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")
    pcm = np.full((48000, 2), 0.02, dtype=np.float32)
    monkeypatch.setattr("avo.breathing.decode_pcm", lambda *a, **k: pcm)
    monkeypatch.setattr(
        "avo.breathing._write_audio",
        lambda p, data, rate: p.write_bytes(data.tobytes()),
    )
    args = build_parser().parse_args(
        [
            "preview",
            "--project",
            str(project),
            "--source",
            str(source),
            "--transcript",
            str(transcript),
            "--control",
            str(control_path),
            "--out-dir",
            str(tmp_path / "edit" / "review" / "v001"),
        ]
    )
    return args, control, control_path, pcm


def test_preview_immutable_and_outside_words_bit_identical(tmp_path, monkeypatch):
    args, _, _, original = _fixture(tmp_path, monkeypatch)
    assert run(args) == 0
    after = np.fromfile(args.out_dir / "after.flac", dtype=np.float32).reshape(-1, 2)
    np.testing.assert_array_equal(after[:24000], original[:24000])
    np.testing.assert_array_equal(after[38400:], original[38400:])
    assert np.max(after[26000:35000]) < 0.01
    manifest = json.loads((args.out_dir / "manifest.json").read_text())
    assert manifest["humanApprovalRequired"]
    with pytest.raises(BreathControlError, match="already exists"):
        run(args)


@pytest.mark.parametrize(
    "change", ["stale-source", "stale-words", "ambiguous", "protected-word"]
)
def test_unsafe_controls_stop_before_writing(tmp_path, monkeypatch, change):
    args, control, path, _ = _fixture(tmp_path, monkeypatch)
    if change == "stale-source":
        control["sourceSha256"] = "0" * 64
    elif change == "stale-words":
        control["transcriptSha256"] = "0" * 64
    elif change == "ambiguous":
        control["events"][0]["status"] = "ambiguous"
    else:
        control["events"][0]["startSample"] = 4800
        control["events"][0]["endSampleExclusive"] = 9600
    path.write_text(json.dumps(control), encoding="utf-8")
    with pytest.raises(BreathControlError):
        run(args)
    assert not args.out_dir.exists()


def test_apply_disallows_partial_window(tmp_path, monkeypatch):
    args, _, _, _ = _fixture(tmp_path, monkeypatch)
    args.mode, args.start = "apply", 0.1
    with pytest.raises(BreathControlError, match="full dialogue"):
        run(args)
    assert not args.out_dir.exists()


def test_output_cannot_escape_footage_edit_directory(tmp_path, monkeypatch):
    args, _, _, _ = _fixture(tmp_path, monkeypatch)
    args.out_dir = tmp_path / "elsewhere"
    with pytest.raises(BreathControlError, match="edit directory"):
        run(args)


def test_candidate_review_has_only_edge_fades_and_honors_window(tmp_path, monkeypatch):
    from avo.timeline.contracts import content_hash

    args, control, _, pcm = _fixture(tmp_path, monkeypatch)
    analysis = {
        "source": file_fingerprint(args.source),
        "analysis": {"events": control["events"]},
    }
    analysis["analysisSha256"] = content_hash(analysis)
    args.analysis = tmp_path / "analysis.json"
    args.analysis.write_text(json.dumps(analysis), encoding="utf-8")
    args.mode, args.end = "review", 0.4
    with pytest.raises(BreathControlError, match="no candidates"):
        run(args)
    args.end = 1
    assert run(args) == 0
    output = np.fromfile(
        args.out_dir / "candidate-listening.flac", dtype=np.float32
    ).reshape(-1, 2)
    np.testing.assert_array_equal(output[480:-480], pcm[480:-480])
    assert output[0, 0] == output[-1, 0] == 0


def test_raw_words_follow_repeated_source_ranges_and_other_clips():
    words = [{"start": 10, "end": 11, "text": "oi"}]
    ranges = [
        {"start": 10, "end": 12, "source": "main"},
        {"start": 0, "end": 5, "source": "other"},
        {"start": 10, "end": 11, "source": "main"},
    ]
    remapped = remap_raw_words(words, ranges, source_id="main")
    assert [(x["start"], x["end"]) for x in remapped] == [(0, 1), (7, 8)]


def test_contract_requires_explicit_evidence_but_allows_off():
    validate_document({"enabled": False}, "avo.breath-control.schema.json")
    with pytest.raises(ContractError):
        validate_document({"enabled": True}, "avo.breath-control.schema.json")


def test_clock_duration_agreement_does_not_claim_alignment():
    assert (
        _word_clock({"durationSamples": 48000}, 48000)["state"]
        == "requires-word-alignment-review"
    )
    assert (
        _word_clock({"durationSamples": 48000}, 96000)["state"] == "duration-mismatch"
    )


def test_cut_proposals_do_not_write_audio(tmp_path, monkeypatch):
    args, control, path, _ = _fixture(tmp_path, monkeypatch)
    args.mode = "propose-cuts"
    control["action"] = "cut"
    control["events"][0]["rawAnchor"] = {
        "sourceId": "raw",
        "sampleRate": 48000,
        "startSample": 96000,
        "endSampleExclusive": 110400,
    }
    path.write_text(json.dumps(control), encoding="utf-8")
    assert run(args) == 0
    assert list(args.out_dir.glob("*.flac")) == []
    manifest = json.loads((args.out_dir / "manifest.json").read_text())
    assert manifest["requiresCMapApproval"] and not manifest["audioModified"]
    assert manifest["proposals"][0]["startSample"] == 96000
