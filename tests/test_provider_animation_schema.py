from __future__ import annotations
import json
from pathlib import Path
import unittest
from avo.timeline.contracts import validate_document
class ProviderAnimationTests(unittest.TestCase):
 def test_pattern_catalog(self):
  d={"schemaVersion":"1.0.0","scope":"provider","provider":"bishop","patterns":[{"patternId":"c01-c02","name":"Chapter pair","behavior":{"sequence":["chapter-ident","topic-card"]},"contexts":["talking-head-review"],"exclusions":["evidence-fullscreen"],"requiredAssets":[],"accessibility":{"reducedMotion":True},"exemplars":[{"candidateHash":"a"*64,"section":"C01+C02"}],"promotion":{"actor":"creator","promotedAt":"2026-08-13T00:00:00Z","approvalReference":"explicit"}}]}
  validate_document(d,"avo.animation.schema.json")


def test_strict_provider_library_contract():
 from avo.timeline.provider_animation import ProviderAnimationService
 from tests.test_animation_promotion import pattern
 import tempfile
 from pathlib import Path
 with tempfile.TemporaryDirectory() as tmp:
  service=ProviderAnimationService(Path(tmp)/"animation.json",provider="bishop",clock=lambda:"2026-08-13T00:00:00Z")
  proposal=service.propose(pattern(),actor="creator",intent_reference="explicit")
  service.decide(Path(proposal["path"]),decision="approved",actor="creator",reason="approved abstraction")
  validate_document(service.load(),"avo.animation-library.schema.json",root=Path("providers"))


def test_bishop_catalog_promotes_approved_splatoon_chapter_support_pattern():
 root = Path(__file__).resolve().parents[1]
 provider = json.loads((root / "providers/bishop/avo.provider.json").read_text(encoding="utf-8"))
 assert provider["animationLibrary"] == "animations/animation.json"
 catalog_path = root / "providers/bishop" / provider["animationLibrary"]
 catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
 validate_document(catalog, "avo.animation-library.schema.json", root=root / "providers")
 pattern = next(item for item in catalog["patterns"] if item["patternId"] == "bishop-playful-chapter-support")
 assert pattern["provenance"] == {
  "sourceVideoId": "splatoon-raiders",
  "candidateSha256": "1cad4b2ab6d146824c60c0eb6bc3a278047e293688594d58260e5887e477456b",
  "sectionRefs": ["C01", "C02"],
 }
 assert pattern["behavior"]["lifecycle"]["entry"]["durationSeconds"] == 0.4
 assert pattern["behavior"]["lifecycle"]["exit"]["durationSeconds"] == 0.24
 assert pattern["behavior"]["durationProfiles"]["comicBeatSeconds"] == 1.6
 assert pattern["behavior"]["sfxRelationships"]["trembleEntry"]["sync"] == "first-frame"
 assert pattern["behavior"]["layout"]["faceAvoidance"] == "required-per-cue"
