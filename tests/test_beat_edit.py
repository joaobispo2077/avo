from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "beat_edit"

from avo import beat_edit, beat_edit_vision, transcribe
from avo.loudness_profiles import PROFILE_TO_PRESET
from jsonschema_support import validator_for


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TechniqueMapSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "avo.technique-map.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.validator = validator_for(schema)

    def test_valid_fixture_passes(self) -> None:
        self.assertEqual(
            list(self.validator.iter_errors(_load("technique-map.valid.json"))), []
        )

    def test_unknown_technique_fails_schema(self) -> None:
        errors = list(
            self.validator.iter_errors(_load("technique-map.invalid-technique.json"))
        )
        self.assertTrue(errors)

    def test_time_after_duration_fails_python_validate(self) -> None:
        errors = beat_edit.validate_map(_load("technique-map.invalid-time.json"))
        self.assertTrue(any("exceeds duration" in item for item in errors))


class BeatEditCliTests(unittest.TestCase):
    def test_validate_ok_and_fail(self) -> None:
        self.assertEqual(
            beat_edit.main(
                ["validate", "--map", str(FIXTURES / "technique-map.valid.json")]
            ),
            0,
        )
        self.assertEqual(
            beat_edit.main(
                [
                    "validate",
                    "--map",
                    str(FIXTURES / "technique-map.invalid-technique.json"),
                ]
            ),
            1,
        )

    def test_probe_wraps_ffprobe(self) -> None:
        probe_json = json.dumps(
            {
                "format": {"duration": "8.0"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "vp9",
                        "width": 1080,
                        "height": 1080,
                        "avg_frame_rate": "30/1",
                    }
                ],
            }
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            edit = root / "edit"
            result = SimpleNamespace(returncode=0, stdout=probe_json, stderr="")
            with patch("avo.beat_edit.subprocess.run", return_value=result):
                with patch(
                    "avo.beat_edit.file_fingerprint",
                    return_value={"sha256": "a" * 64, "sizeBytes": 5},
                ):
                    code = beat_edit.main(
                        [
                            "probe",
                            "--input",
                            str(media),
                            "--edit-dir",
                            str(edit),
                        ]
                    )
            self.assertEqual(code, 0)
            payload = json.loads(
                (edit / "timeline" / "reference-probe.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["aspect"], "1:1")
            self.assertEqual(payload["fps"], 30.0)

    def test_grid_missing_script(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "music-to-video"):
                beat_edit.find_analyze_beatgrid(Path(tmp))

    def test_pacing_metronome_is_phrase_flow(self) -> None:
        audiomap = _load("audiomap.json")
        audiomap["grid"]["beats_sec"] = [i * 0.5 for i in range(16)]
        audiomap["key_moments"] = []
        self.assertEqual(beat_edit.infer_pacing(audiomap), "phrase_flow")

    def test_merge_empty_transcript_and_vocabulary(self) -> None:
        probe_doc = {
            "path": "clip.mp4",
            "sha256": "a" * 64,
            "durationSec": 8.0,
            "width": 1080,
            "height": 1080,
            "fps": 30,
            "aspect": "1:1",
            "codec": "vp9",
        }
        document = beat_edit.merge(
            probe_doc=probe_doc,
            audiomap=_load("audiomap.json"),
            labels=_load("vision.labels.json"),
            transcript=_load("transcript.empty.json"),
            video_id="demo",
            provider="bishop",
        )
        self.assertEqual(document["vocabulary"]["flip_3d"], "absent")
        self.assertEqual(document["vocabulary"]["card_carousel"], "present")
        self.assertFalse(beat_edit.validate_map(document))
        self.assertEqual(len(document["events"]), 3)

    def test_inventory_assign_recycle_and_leftovers(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "inserts"
            folder.mkdir()
            (folder / "a.jpg").write_bytes(b"one")
            (folder / "b.png").write_bytes(b"two")
            (folder / "c.gif").write_bytes(b"gif")
            (folder / "notes.txt").write_text("skip", encoding="utf-8")
            inv = beat_edit.inventory(folder)
            self.assertEqual(len(inv["files"]), 3)
            self.assertEqual(inv["skipped"], ["notes.txt"])
            technique_map = _load("technique-map.valid.json")
            while len(technique_map["events"]) < 5:
                extra = json.loads(json.dumps(technique_map["events"][0]))
                extra["id"] = f"e-{len(technique_map['events']):03d}"
                technique_map["events"].append(extra)
            assigned = beat_edit.assign(technique_map, inv)
            self.assertEqual(assigned["recycleCount"], 2)
            self.assertEqual(assigned["unused"], [])

    def test_assign_rejects_reference_sha(self) -> None:
        technique_map = _load("technique-map.valid.json")
        inv = {
            "files": [
                {
                    "path": "ref.mp4",
                    "kind": "video",
                    "sha256": technique_map["source"]["sha256"],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "allow-reference"):
            beat_edit.assign(technique_map, inv)

    def test_snap_rejects_large_duration_ratio(self) -> None:
        technique_map = _load("technique-map.valid.json")
        new_map = _load("audiomap.json")
        new_map["audio"]["duration_sec"] = 40.0
        with self.assertRaisesRegex(ValueError, "duration ratio"):
            beat_edit.snap(technique_map, new_map)

    def test_snap_reanchors_when_ratio_ok(self) -> None:
        technique_map = _load("technique-map.valid.json")
        new_map = _load("audiomap.json")
        new_map["audio"]["duration_sec"] = 8.0
        snapped = beat_edit.snap(technique_map, new_map)
        self.assertEqual(snapped["events"][0]["t"], 0.0)

    def test_flash_flags_dense_whips(self) -> None:
        document = _load("technique-map.valid.json")
        document["events"] = [
            {
                "id": f"e-{i:03d}",
                "t": 1.0 + i * 0.2,
                "tEnd": 1.2 + i * 0.2,
                "anchor": f"t:{i}",
                "techniques": ["whip_bump"],
                "insertSlot": f"slot-{i}",
                "confidence": 1.0,
            }
            for i in range(5)
        ]
        document["vocabulary"]["whip_bump"] = "present"
        flagged = beat_edit.flash_flags(document)
        self.assertTrue(flagged["safety"]["whipFlashFlag"])

    def test_source_log_and_docs(self) -> None:
        with TemporaryDirectory() as tmp:
            edit = Path(tmp)
            beat_edit.append_source_log(
                edit,
                [
                    {
                        "asset": "reference",
                        "role": "timing reference",
                        "path": "clip.mp4",
                        "note": "reused-content / commentary",
                    }
                ],
            )
            log = (edit / "SOURCE-LOG.md").read_text(encoding="utf-8")
            self.assertIn("clip.mp4", log)
            docs = beat_edit.write_docs(
                _load("technique-map.valid.json"), edit / "review" / "technique-map.md"
            )
            self.assertIn("card_carousel", docs.read_text(encoding="utf-8"))

    def test_canvas_defaults(self) -> None:
        self.assertEqual(beat_edit.canvas_for({"source": {"aspect": "9:16"}}), "9:16")
        self.assertEqual(
            beat_edit.canvas_for(None, {"deliverable": {"aspect": "16:9"}}), "16:9"
        )
        self.assertEqual(beat_edit.canvas_for(None, None), "1:1")
        starter = beat_edit.starter_map(
            video_id="demo", provider="bishop", duration_sec=8.0, aspect="1:1"
        )
        self.assertEqual(starter["vocabulary"]["card_carousel"], "present")
        self.assertFalse(beat_edit.validate_map(starter))

    def test_profile_maps_to_music_loudness(self) -> None:
        self.assertEqual(PROFILE_TO_PRESET["beat-edit"], "music_video")


class BeatEditVisionTests(unittest.TestCase):
    def test_parse_and_label_with_injected_post(self) -> None:
        parsed = beat_edit_vision.parse_label_text(
            '```json\n{"techniques":["punch_zoom","nope"],"confidence":1.2}\n```'
        )
        self.assertEqual(parsed["techniques"], ["punch_zoom"])
        self.assertEqual(parsed["confidence"], 1.0)
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            still = folder / "t-2000.jpg"
            still.write_bytes(b"jpeg")

            def fake_post(_url: str, _payload: dict) -> dict:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"techniques":["stylize"],"confidence":0.4}'
                            }
                        }
                    ]
                }

            labeled = beat_edit_vision.label_frames_dir(
                folder,
                post=fake_post,
                pin={
                    "url": "http://127.0.0.1:8090/v1",
                    "model": "prism-ml/bonsai-27b",
                    "id": "bonsai-27b-gguf",
                },
            )
            self.assertEqual(labeled["frames"][0]["t"], 2.0)
            self.assertEqual(labeled["frames"][0]["techniques"], ["stylize"])
            self.assertEqual(len(labeled["promptHash"]), 64)

    def test_unreachable_endpoint_fails_closed(self) -> None:
        from urllib.error import URLError

        with TemporaryDirectory() as tmp:
            still = Path(tmp) / "t-0000.jpg"
            still.write_bytes(b"jpeg")
            with patch(
                "avo.beat_edit_vision.urlopen",
                side_effect=URLError("down"),
            ):
                with self.assertRaisesRegex(RuntimeError, "endpoint unreachable"):
                    beat_edit_vision.label_image(
                        still,
                        url="http://127.0.0.1:8090/v1",
                        model="prism-ml/bonsai-27b",
                    )

    def test_missing_endpoint_fails_closed(self) -> None:
        resolved = SimpleNamespace(id="qwen2.5-7b", pin={})
        with (
            patch("avo.model_sources.resolve_job", return_value=resolved),
            patch("avo.model_sources.preflight"),
            patch.dict("os.environ", {"WATCHSKILL_CUSTOM_BASE_URL": ""}),
        ):
            with self.assertRaisesRegex(RuntimeError, "endpoint is unset"):
                beat_edit_vision.require_bonsai()


class TranscribeLanguageTests(unittest.TestCase):
    def test_resolve_language_aliases(self) -> None:
        self.assertEqual(transcribe.resolve_language(None)[1], "pt-BR")
        self.assertEqual(transcribe.resolve_language("en")[0], "en")
        self.assertIsNone(transcribe.resolve_language("auto")[0])

    def test_runtime_honors_english(self) -> None:
        class FakeWhisperModel:
            transcribe_args = None

            def __init__(self, model_path: str, **kwargs):
                pass

            def transcribe(self, media: str, **kwargs):
                FakeWhisperModel.transcribe_args = kwargs
                return iter([]), types.SimpleNamespace(language="en")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "small"
            model_dir.mkdir()
            for name in transcribe.MODEL_FILES:
                (model_dir / name).write_text(name)
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = FakeWhisperModel
            video = root / "clip.mp4"
            video.write_bytes(b"media")
            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                runtime = transcribe.LocalTranscriber(
                    model_dir=model_dir, language="en"
                )
                payload = runtime.transcribe(
                    video, transcribe.source_fingerprint(video)
                )
            self.assertEqual(FakeWhisperModel.transcribe_args["language"], "en")
            self.assertEqual(payload["language_code"], "en-US")

    def test_project_language_en_is_used(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "avo.project.json").write_text(
                json.dumps(
                    {
                        "provider": "bishop",
                        "rawDir": str(root),
                        "transcription": {"language": "en"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(transcribe.language_from_project(root / "edit"), "en")


if __name__ == "__main__":
    unittest.main()
