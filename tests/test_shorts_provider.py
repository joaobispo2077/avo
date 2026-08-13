from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from avo import shorts_provider


class ShortsProviderTests(unittest.TestCase):
    def test_palette_maps_to_hyperframes_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider_dir = root / "providers" / "demo"
            palette_dir = provider_dir / "brand"
            palette_dir.mkdir(parents=True)
            (provider_dir / "avo.provider.json").write_text(json.dumps({
                "name": "demo",
                "brand": {"palette": "providers/demo/brand/palette.json"},
            }), encoding="utf-8")
            (palette_dir / "palette.json").write_text(json.dumps({
                "accent": "#112233",
                "text": "#eeeeee",
                "secondary": "#444444",
                "roles": {
                    "captionFill": "#fafafa",
                    "captionRail": "rgba(1, 2, 3, 0.9)",
                    "punch": "#ff0000",
                    "font": "Inter",
                    "railWidth": "800px",
                },
            }), encoding="utf-8")
            tokens = shorts_provider.load_provider_design_tokens("demo", root=root)
            self.assertEqual(tokens["ink"], "#fafafa")
            self.assertEqual(tokens["accent"], "#112233")
            self.assertEqual(tokens["punch"], "#ff0000")
            self.assertEqual(tokens["font"], "Inter")
            fingerprint = shorts_provider.provider_tokens_fingerprint(tokens)
            self.assertIsNotNone(fingerprint)
            self.assertEqual(len(fingerprint), 64)

    def test_missing_provider_returns_empty_tokens(self) -> None:
        self.assertEqual(shorts_provider.load_provider_design_tokens("missing-provider"), {})


if __name__ == "__main__":
    unittest.main()
