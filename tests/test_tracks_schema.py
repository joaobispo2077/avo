from __future__ import annotations
import unittest
from avo.timeline.contracts import ContractError,validate_document
SHA = "a" * 64
def doc():
 return {"schemaVersion":"1.0.0","artifactType":"tracks","artifactId":"assembly","videoId":"v","provider":"bishop","timelineDomain":"cmap-output","currentRevisionId":"r1","approvedRevisionId":None,"revisions":[{"revisionId":"r1","parentRevisionId":None,"createdAt":"2026-08-13T00:00:00Z","actor":"agent","reason":"assembly","snapshot":{"basis":{"artifactType":"bmap","artifactId":"beats","revisionId":"b1","sha256":SHA,"state":"valid"},"audioTracks":{"layers":[{"layerId":"dialogue","order":0,"role":"dialogue","source":{"sha256":SHA,"sizeBytes":1,"generator":"base-program"},"regions":[{"regionId":"region-dialogue","startTicks":0,"endTicks":1000,"cueIds":["q1"]}],"channels":[0,1],"gainDb":0,"mute":False,"loudnessIntent":"dialogue-lead"}]},"videoTracks":{"layers":[{"layerId":"base","order":0,"role":"base","source":{"sha256":SHA,"sizeBytes":1,"generator":"base-program"},"regions":[{"regionId":"region-base","startTicks":0,"endTicks":1000,"cueIds":["q1"]}],"zOrder":0,"fit":"contain","safeZones":["face"],"faceAvoidance":True}]}},"diff":[],"dependencies":[],"contentHash":"b"*64,"evidence":[],"state":"draft"}],"decisions":[]}
class TracksSchemaTests(unittest.TestCase):
 def test_valid(self):validate_document(doc(),"avo.tracks.schema.json")
 def test_unknown_layer_field_rejected(self):
  d=doc();d["revisions"][0]["snapshot"]["audioTracks"]["layers"][0]["secret"]=1
  with self.assertRaises(ContractError):validate_document(d,"avo.tracks.schema.json")
