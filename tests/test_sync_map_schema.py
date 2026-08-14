from __future__ import annotations
import unittest
from avo.timeline.contracts import ContractError,validate_document
def doc():
 return {"schemaVersion":"1.0.0","artifactType":"sync-map","artifactId":"sync","videoId":"v","provider":"bishop","timelineDomain":"raw-source","currentRevisionId":"r1","approvedRevisionId":None,"revisions":[{"revisionId":"r1","parentRevisionId":None,"createdAt":"2026-08-13T00:00:00Z","actor":"agent","reason":"sync","snapshot":{"picture":{"sourceId":"cam","fingerprint":{"sha256":"a"*64,"sizeBytes":1},"stream":"v:0"},"audio":{"sourceId":"mic","fingerprint":{"sha256":"b"*64,"sizeBytes":1},"stream":"a:0","channels":[0]},"referenceClock":"picture","signConvention":"positive-audio-delay","transform":{"kind":"constant-offset","offsetTicks":128,"timebase":{"num":1,"den":1000}},"calibrationSamples":[{"pictureTicks":0,"audioTicks":-128,"residualTicks":0},{"pictureTicks":1000,"audioTicks":872,"residualTicks":0},{"pictureTicks":2000,"audioTicks":1872,"residualTicks":0}],"toleranceTicks":40,"fullProgramValidation":{"status":"pass","maxResidualTicks":20}},"diff":[],"dependencies":[],"contentHash":"c"*64,"evidence":[],"state":"draft"}],"decisions":[]}
class SyncSchemaTests(unittest.TestCase):
 def test_valid(self): validate_document(doc(),"avo.sync-map.schema.json")
 def test_full_program_required(self):
  d=doc();del d["revisions"][0]["snapshot"]["fullProgramValidation"]
  with self.assertRaises(ContractError):validate_document(d,"avo.sync-map.schema.json")

 def test_ambiguous_sign_is_rejected(self):
  d=doc();d["revisions"][0]["snapshot"]["signConvention"]="unknown"
  with self.assertRaises(ContractError):validate_document(d,"avo.sync-map.schema.json")
 def test_transform_rejects_unknown_fields(self):
  d=doc();d["revisions"][0]["snapshot"]["transform"]["custom"]=True
  with self.assertRaises(ContractError):validate_document(d,"avo.sync-map.schema.json")
 def test_not_applicable_requires_reason_actor_and_basis(self):
  valid={"status":"not-applicable","rawFingerprints":{"muxed":"a"*64},"assessedBy":"agent","rationale":"single muxed clock","policy":"single-muxed-clock-only"}
  validate_document(valid,"avo.sync-map.schema.json#/$defs/syncNotApplicable")
  for key in ("rawFingerprints","assessedBy","rationale"):
   value=dict(valid);del value[key]
   with self.assertRaises(ContractError):validate_document(value,"avo.sync-map.schema.json#/$defs/syncNotApplicable")
