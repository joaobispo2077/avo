from __future__ import annotations
import unittest
from avo.timeline.tracks import TrackError,resolve_tracks
class TraceTests(unittest.TestCase):
 def test_missing_cue_blocks(self):
  with self.assertRaises(TrackError):resolve_tracks({"audioTracks":{"layers":[{"layerId":"x","regions":[{"cueIds":["missing"]}],"source":{"sha256":"a"*64}}]},"videoTracks":{"layers":[]}},{"q"})
 def test_mismatch_blocks(self):
  with self.assertRaises(TrackError):resolve_tracks({"audioTracks":{"layers":[{"layerId":"x","regions":[{"cueIds":["q"]}],"source":{"sha256":"a"*64,"actualSha256":"b"*64}}]},"videoTracks":{"layers":[]}},{"q"})


def test_post_encode_audit_flags_renderer_ignored_layer():
    from avo.timeline.tracks import audit_contributions
    snapshot = {
        "audioTracks": {"layers": [{"layerId": "dialogue"}]},
        "videoTracks": {"layers": [{"layerId": "base"}, {"layerId": "card"}]},
    }
    report = audit_contributions(
        snapshot,
        [{"layerId": "dialogue", "enabled": True}, {"layerId": "base", "enabled": True}],
    )
    assert report["status"] == "fail"
    assert report["missing"] == ["card"]
