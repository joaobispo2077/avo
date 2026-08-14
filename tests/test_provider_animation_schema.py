from __future__ import annotations

import json
import unittest
from pathlib import Path

from avo.timeline.contracts import validate_document
from avo.timeline.provider_animation import ProviderAnimationService
from tests.test_animation_promotion import pattern


class ProviderAnimationTests(unittest.TestCase):
    def test_pattern_catalog_schema(self):
        document = {
            "schemaVersion": "1.0.0",
            "scope": "provider",
            "provider": "example",
            "patterns": [
                {
                    "patternId": "c01-c02",
                    "name": "Chapter pair",
                    "behavior": {"sequence": ["chapter-ident", "topic-card"]},
                    "contexts": ["talking-head-review"],
                    "exclusions": ["evidence-fullscreen"],
                    "requiredAssets": [],
                    "accessibility": {"reducedMotion": True},
                    "exemplars": [{"candidateHash": "a" * 64, "section": "C01+C02"}],
                    "promotion": {
                        "actor": "creator",
                        "promotedAt": "2026-08-13T00:00:00Z",
                        "approvalReference": "explicit",
                    },
                }
            ],
        }
        validate_document(document, "avo.animation.schema.json")


def test_strict_provider_library_contract(tmp_path: Path):
    service = ProviderAnimationService(
        tmp_path / "animation.json",
        provider="example",
        clock=lambda: "2026-08-13T00:00:00Z",
    )
    proposal = service.propose(pattern(), actor="creator", intent_reference="explicit")
    service.decide(
        Path(proposal["path"]),
        decision="approved",
        actor="creator",
        reason="approved abstraction",
    )
    validate_document(
        service.load(),
        "avo.animation-library.schema.json",
        root=Path("providers"),
    )


def _kit_pattern() -> dict:
    return {
        "patternId": "playful-chapter-support",
        "name": "Playful chapter support overlays",
        "version": "1.2.0",
        "behavior": {
            "sequence": ["chapter-identification", "topic-support-cards", "comic-beat"],
            "lifecycle": {
                "entry": {"motion": "tremble-pop", "durationSeconds": 0.4},
                "hold": {"motion": "stable-readable"},
                "exit": {"motion": "resolved-fade", "durationSeconds": 0.24},
            },
            "durationProfiles": {
                "commonCardSecondsMin": 5.3,
                "commonCardSecondsMax": 8.4,
                "comicBeatSeconds": 1.6,
            },
            "layout": {
                "rail": "open-space-primary",
                "commonCardMaxWidthPx": 540,
                "faceAvoidance": "required-per-cue",
            },
            "motionRecipes": {"tremble": {"totalEntrySeconds": 0.42}},
            "styleTokens": {"colors": {"cyan": "#19d8ff"}},
            "comicBeat": {
                "ideaId": "premature-rating-question",
                "layout": {
                    "meme": {"anchor": "far-right"},
                    "questionPlaque": {"anchor": "chest"},
                },
            },
            "sfxRelationships": {"trembleEntry": {"role": "pop", "sync": "first-frame"}},
            "hyperframesKit": {
                "root": "hyperframes/playful-chapter-support",
                "css": "playful.css",
                "motion": "playful-motion.js",
                "manifest": "MANIFEST.json",
                "api": "PlayfulMotion",
                "slots": ["panel-card", "comic-beat"],
            },
        },
        "contexts": ["talking-head-review"],
        "exclusions": ["evidence-fullscreen", "face-overlap"],
        "requiredAssets": ["chapter-label", "hyperframes-kit"],
        "accessibility": {"reducedMotion": True, "flashingSafe": True},
        "provenance": {
            "sourceVideoId": "example-source-video",
            "candidateSha256": "b" * 64,
            "sectionRefs": ["C01", "C02"],
        },
    }


def test_promoted_pattern_can_link_tmp_hyperframes_kit(tmp_path: Path):
    """Logic: promote sanitized pattern + relative kit files. No real provider/video data."""
    catalog_path = tmp_path / "animation.json"
    kit_root = tmp_path / "hyperframes" / "playful-chapter-support"
    (kit_root / "slots").mkdir(parents=True)
    (kit_root / "playful.css").write_text(".panel{}", encoding="utf-8")
    (kit_root / "playful-motion.js").write_text("globalThis.PlayfulMotion={};", encoding="utf-8")
    (kit_root / "slots" / "comic-beat.html").write_text(
        "<div class=\"comic\">{{QUESTION}}</div>",
        encoding="utf-8",
    )
    (kit_root / "MANIFEST.json").write_text(
        json.dumps({"kitId": "playful-chapter-support", "version": "1.2.0"}),
        encoding="utf-8",
    )

    service = ProviderAnimationService(
        catalog_path,
        provider="example",
        clock=lambda: "2026-08-14T00:00:00Z",
    )
    proposal = service.propose(
        _kit_pattern(),
        actor="creator",
        intent_reference="explicit kit promotion",
    )
    service.decide(
        Path(proposal["path"]),
        decision="approved",
        actor="creator",
        reason="sanitized kit-linked pattern",
    )

    catalog = service.load()
    validate_document(catalog, "avo.animation-library.schema.json", root=Path("providers"))
    item = catalog["patterns"][0]

    assert item["patternId"] == "playful-chapter-support"
    assert item["behavior"]["lifecycle"]["entry"]["durationSeconds"] == 0.4
    assert item["behavior"]["lifecycle"]["exit"]["durationSeconds"] == 0.24
    assert item["behavior"]["durationProfiles"]["comicBeatSeconds"] == 1.6
    assert item["behavior"]["sfxRelationships"]["trembleEntry"]["sync"] == "first-frame"
    assert item["behavior"]["layout"]["faceAvoidance"] == "required-per-cue"
    assert item["behavior"]["comicBeat"]["ideaId"] == "premature-rating-question"
    assert item["behavior"]["hyperframesKit"]["css"] == "playful.css"
    assert "comic-beat" in item["behavior"]["hyperframesKit"]["slots"]

    linked = catalog_path.parent / item["behavior"]["hyperframesKit"]["root"]
    assert (linked / item["behavior"]["hyperframesKit"]["css"]).is_file()
    assert (linked / item["behavior"]["hyperframesKit"]["motion"]).is_file()
    assert (linked / "slots" / "comic-beat.html").is_file()

    serialized = json.dumps(item)
    assert ".png" not in serialized
    assert ".mp4" not in serialized
    assert "splatoon" not in serialized.lower()
