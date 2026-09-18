from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from avo.adapters.motion.hyperframes import (
    HyperframesAdapter,
    HyperframesError,
    build_composition_spec,
    compile_project,
)


def asset(path: Path, muted: bool) -> dict:
    path.write_bytes(path.name.encode())
    return {
        "path": str(path),
        "hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "durationSec": 2,
        "muted": muted,
    }


PHRASES = [
    {
        "id": "phrase-1",
        "startSec": 0,
        "endSec": 1.8,
        "renderedText": "Switch OLED",
        "words": [
            {
                "id": "p1-w1",
                "text": "Switch",
                "startSec": 0,
                "endSec": 0.7,
                "punch": False,
                "highlightEnterSec": 0,
                "highlightExitSec": 0.7,
            },
            {
                "id": "p1-w2",
                "text": "OLED",
                "startSec": 0.7,
                "endSec": 1.4,
                "punch": True,
                "highlightEnterSec": 0.7,
                "highlightExitSec": 1.4,
            },
        ],
        "autofixes": [],
    }
]


class HyperframesAdapterTests(unittest.TestCase):
    def test_compiler_emits_direct_root_muted_video_separate_audio_and_local_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "baseVideo": asset(root / "video.mp4", True),
                "dialogueAudio": asset(root / "audio.m4a", False),
            }
            item = {
                "id": "01",
                "editedDurationSec": 2,
                "captions": PHRASES,
                "layout": {"mode": "full-frame", "captionAnchor": "bottom"},
                "factualReviewReferences": ["review:1"],
            }
            spec = build_composition_spec(
                batch_id="batch",
                item=item,
                output={"width": 1080, "height": 1920, "fps": 30},
                assets=assets,
                proof_revision=1,
                expected_output_path=root / "proof.mp4",
            )
            project = compile_project(spec, root / "project")
            page = (project / "index.html").read_text(encoding="utf-8")
            self.assertIn('src="assets/gsap.min.js"', page)
            self.assertNotIn("https://", page)
            self.assertRegex(page, r'<main[\s\S]*?<video[^>]+id="base-video"')
            self.assertIn("muted", page)
            self.assertIn('<audio\n        id="dialogue-audio"', page)
            self.assertEqual(page.count("gsap.timeline({ paused: true })"), 1)
            self.assertEqual(
                (project / "runtime.js").read_text().count("gsap.timeline"), 0
            )
            self.assertNotIn("COMPARATIVO SEM HYPE", page)
            self.assertNotIn("GAMEPLAY ILUSTRATIVA", page)
            self.assertIn('id="base-wrap"', page)
            self.assertIn('id="callout-layer"', page)
            self.assertNotIn('id="insertion-audio"', page)
            self.assertIn('lang="und"', page)
            self.assertIn('aria-label="Captions"', page)
            self.assertNotIn("Legendas em português", page)
            manifest = json.loads(
                (project / "hyperframes.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["renderContract"]["width"], 1080)
            self.assertEqual(manifest["renderContract"]["height"], 1920)

    def test_callouts_and_punchins_compile_into_existing_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "baseVideo": asset(root / "video.mp4", True),
                "dialogueAudio": asset(root / "audio.m4a", False),
            }
            item = {
                "id": "01",
                "editedDurationSec": 2,
                "captions": PHRASES,
                "layout": {"mode": "full-frame", "captionAnchor": "top"},
                "factualReviewReferences": ["review:1"],
                "callouts": [
                    {
                        "id": "chip-teen",
                        "kind": "chip",
                        "text": "US Teen",
                        "startSec": 0.4,
                        "endSec": 1.6,
                        "corner": "bl",
                    },
                    {
                        "id": "stamp-starfox",
                        "kind": "stamp",
                        "text": "STAR FOX",
                        "startSec": 0.8,
                        "endSec": 2.0,
                        "corner": "br",
                    },
                ],
                "punchIns": [
                    {
                        "id": "punch-box",
                        "startSec": 0.8,
                        "endSec": 1.6,
                        "scale": 1.08,
                    }
                ],
            }
            spec = build_composition_spec(
                batch_id="batch",
                item=item,
                output={"width": 1080, "height": 1920, "fps": 30},
                assets=assets,
                proof_revision=1,
                expected_output_path=root / "proof.mp4",
            )
            project = compile_project(spec, root / "project")
            page = (project / "index.html").read_text(encoding="utf-8")
            runtime = (project / "runtime.js").read_text(encoding="utf-8")
            self.assertIn("US Teen", page)
            self.assertIn("STAR FOX", page)
            self.assertIn("chip-teen", runtime)
            self.assertIn("punch-box", runtime)
            self.assertEqual(runtime.count("gsap.timeline"), 0)
            self.assertNotIn('id="insertion-audio"', page)

    def test_sfx_hits_compile_to_framework_owned_audio_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "baseVideo": asset(root / "video.mp4", True),
                "dialogueAudio": asset(root / "audio.m4a", False),
                "sfxChip": asset(root / "sfx-chip.m4a", False),
                "sfxStamp": asset(root / "sfx-stamp.m4a", False),
            }
            assets["sfxChip"]["durationSec"] = 0.44
            assets["sfxStamp"]["durationSec"] = 0.44
            item = {
                "id": "01",
                "editedDurationSec": 2,
                "captions": PHRASES,
                "layout": {"mode": "full-frame", "captionAnchor": "top"},
                "factualReviewReferences": ["review:1"],
                "sfxHits": [
                    {"id": "s01-chip-sfx", "kind": "chip", "startSec": 0.4},
                    {"id": "s01-stamp-sfx", "kind": "stamp", "startSec": 1.8},
                ],
            }
            spec = build_composition_spec(
                batch_id="batch",
                item=item,
                output={"width": 1080, "height": 1920, "fps": 30},
                assets=assets,
                proof_revision=1,
                expected_output_path=root / "proof.mp4",
            )
            project = compile_project(spec, root / "project")
            page = (project / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="s01-chip-sfx"', page)
            self.assertIn('src="assets/sfx-chip.m4a"', page)
            self.assertIn('data-track-index="20"', page)
            self.assertIn('data-start="1.800000"', page)
            self.assertTrue((project / "assets" / "sfx-chip.m4a").is_file())
            self.assertIn('data-duration="0.200000"', page)

    def test_split_geometry_requires_two_complete_regions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "baseVideo": asset(root / "v.mp4", True),
                "dialogueAudio": asset(root / "a.m4a", False),
            }
            item = {
                "id": "01",
                "editedDurationSec": 2,
                "captions": [],
                "layout": {"mode": "split", "captionAnchor": "seam", "splitRatio": 0.5},
            }
            with self.assertRaises(HyperframesError):
                build_composition_spec(
                    batch_id="b",
                    item=item,
                    output={"width": 1080, "height": 1920, "fps": 30},
                    assets=assets,
                    proof_revision=1,
                    expected_output_path=root / "x.mp4",
                )

    def test_subprocess_adapter_adds_strict_and_propagates_failure(self) -> None:
        calls = []

        def runner(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(argv, 7, "out", "bad composition")

        result = HyperframesAdapter(runner=runner).execute(
            "check", Path("/tmp/project"), root=Path.cwd()
        )
        self.assertEqual(result.exit_code, 7)
        self.assertIn("--strict", calls[0][0])
        self.assertEqual(result.stderr, "bad composition")

    def test_caption_words_are_inline_block_without_negative_tracking(self) -> None:
        css = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "avo"
            / "templates"
            / "shorts_hyperframes"
            / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertIn("display: inline-block;", css)
        self.assertNotIn("letter-spacing: -1.2px;", css)

    def test_stars_widget_compiles_fill_stagger_and_markup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "baseVideo": asset(root / "video.mp4", True),
                "dialogueAudio": asset(root / "audio.m4a", False),
            }
            item = {
                "id": "05",
                "editedDurationSec": 2,
                "captions": PHRASES,
                "layout": {"mode": "full-frame", "captionAnchor": "bottom"},
                "factualReviewReferences": ["review:1"],
                "graphics": [
                    {
                        "id": "s05-stars-backlog",
                        "widget": "stars",
                        "startSec": 0.4,
                        "endSec": 1.9,
                        "corner": "br",
                        "params": {
                            "total": 5,
                            "filled": 4,
                            "label": "Backlog 4/5",
                            "fillStaggerSec": 0.12,
                        },
                        "sfx": {"kind": "chip", "every": "fill"},
                    }
                ],
            }
            spec = build_composition_spec(
                batch_id="batch",
                item=item,
                output={"width": 1080, "height": 1920, "fps": 30},
                assets=assets,
                proof_revision=1,
                expected_output_path=root / "proof.mp4",
            )
            project = compile_project(spec, root / "project")
            page = (project / "index.html").read_text(encoding="utf-8")
            runtime = (project / "runtime.js").read_text(encoding="utf-8")
            self.assertIn('id="s05-stars-backlog"', page)
            self.assertIn('id="s05-stars-backlog-star-5"', page)
            self.assertIn("Backlog 4/5", page)
            self.assertNotIn("Backloggd", page)
            self.assertEqual(page.count('class="graphic-star"'), 5)
            self.assertIn('"fillStaggerSec":0.12', runtime)
            self.assertIn('"filled":4', runtime)
            self.assertIn("driveStars", runtime)
            self.assertIn("scaleY: 1", runtime)
            self.assertEqual(runtime.count("gsap.timeline"), 0)
            self.assertIn("prefers-reduced-motion", runtime)

    def test_catalog_widgets_compile(self) -> None:
        widgets = [
            {
                "id": "w-stack",
                "widget": "stack-resolve",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bc",
                "params": {
                    "items": [{"text": "Orbitals", "startSec": 0.2}],
                    "resolve": "STAR FOX",
                    "resolveAtSec": 1.2,
                },
            },
            {
                "id": "w-vs",
                "widget": "vs-reject",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bl",
                "params": {
                    "reject": {"text": "GAME-KEY", "atSec": 0.2},
                    "confirm": {"text": "CARTUCHO", "atSec": 0.8},
                    "badge": {"text": "US Teen", "atSec": 1.2},
                },
            },
            {
                "id": "w-flip",
                "widget": "flip-180",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "br",
                "params": {"front": "arte", "back": "arte invertida"},
            },
            {
                "id": "w-wipe",
                "widget": "cover-wipe",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bl",
                "params": {
                    "cover": "caixa vermelha",
                    "hidden": "outra arte",
                    "wipeAtSec": 0.8,
                },
            },
            {
                "id": "w-ratio",
                "widget": "ratio-lock",
                "startSec": 0.2,
                "endSec": 1.4,
                "corner": "bl",
                "params": {"ratio": "1:1"},
            },
            {
                "id": "w-meter",
                "widget": "duration-meter",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bl",
                "params": {
                    "label": "6h",
                    "ticks": 3,
                    "metacritic": "80–81?",
                    "metacriticAtSec": 1.4,
                },
            },
            {
                "id": "w-roles",
                "widget": "two-roles",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bl",
                "params": {
                    "roles": ["VOA", "MIRA"],
                    "downbeat": "desperdício",
                    "downbeatAtSec": 1.2,
                },
            },
            {
                "id": "w-badges",
                "widget": "badge-pair",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bl",
                "params": {
                    "badges": [
                        {"text": "Switch 2 Pro", "atSec": 0.2},
                        {"text": "PT-BR dublado", "atSec": 1.0},
                    ]
                },
            },
            {
                "id": "w-price",
                "widget": "price-duel",
                "startSec": 0.2,
                "endSec": 1.8,
                "corner": "bc",
                "params": {"physical": "R$269", "digital": "~R$270"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "baseVideo": asset(root / "video.mp4", True),
                "dialogueAudio": asset(root / "audio.m4a", False),
            }
            item = {
                "id": "01",
                "editedDurationSec": 2,
                "captions": PHRASES,
                "layout": {"mode": "full-frame", "captionAnchor": "top"},
                "factualReviewReferences": ["review:1"],
                "graphics": widgets,
            }
            spec = build_composition_spec(
                batch_id="batch",
                item=item,
                output={"width": 1080, "height": 1920, "fps": 30},
                assets=assets,
                proof_revision=1,
                expected_output_path=root / "proof.mp4",
            )
            project = compile_project(spec, root / "project")
            page = (project / "index.html").read_text(encoding="utf-8")
            runtime = (project / "runtime.js").read_text(encoding="utf-8")
            for widget in widgets:
                self.assertIn(f'id="{widget["id"]}"', page)
            self.assertIn("STAR FOX", page)
            self.assertIn("arte invertida", page)
            self.assertIn("caixa vermelha", page)
            self.assertIn("80–81?", page)
            self.assertIn("desperdício", page)
            self.assertIn("PT-BR dublado", page)
            self.assertIn("R$269", page)
            self.assertNotIn("Backloggd", page)
            self.assertIn("driveStackResolve", runtime)
            self.assertIn("drivePriceDuel", runtime)
            self.assertEqual(runtime.count("gsap.timeline"), 0)


if __name__ == "__main__":
    unittest.main()
