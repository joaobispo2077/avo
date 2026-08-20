from __future__ import annotations

import unittest

from avo.timeline.tracks import resolve_tracks


class TracksIntegrationTests(unittest.TestCase):
    def test_resolves_ordered_layers(self):
        s = {
            "audioTracks": {
                "layers": [
                    {
                        "layerId": "music",
                        "order": 2,
                        "source": {"sha256": "a" * 64},
                        "regions": [{"cueIds": ["m"]}],
                    },
                    {
                        "layerId": "dialogue",
                        "order": 0,
                        "source": {"sha256": "b" * 64},
                        "regions": [{"cueIds": ["d"]}],
                    },
                ]
            },
            "videoTracks": {"layers": []},
        }
        r = resolve_tracks(s, {"m", "d"})
        self.assertEqual(
            [x["layerId"] for x in r["audioTracks"]["layers"]], ["dialogue", "music"]
        )
