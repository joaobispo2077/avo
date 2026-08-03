"""Tests for provider video registry stubs."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from avo import init_project, stats, video_registry
from avo.paths import repo_root


def _external_raw(name: str) -> Path:
    """Portable absolute external path (works on Linux CI and Windows)."""
    return Path(tempfile.gettempdir()) / "avo-test-footage" / name


class VideoRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.provider_dir = self.root / "providers" / "_template"
        self.provider_dir.mkdir(parents=True)
        (self.provider_dir / "avo.provider.json").write_text(
            json.dumps({"name": "_template", "kind": "youtube", "media": {"rawRoot": "/ext"}}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_and_list_registry(self) -> None:
        raw = _external_raw("demo-one")
        reg = video_registry.write_registry(
            "_template",
            "demo-one",
            raw,
            title="Demo",
            root=self.root,
        )
        self.assertTrue(reg.is_file())
        entries = video_registry.list_videos("_template", root=self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "demo-one")

    def test_rejects_repo_internal_raw_dir(self) -> None:
        internal = repo_root() / ".test-internal-footage"
        with self.assertRaises(video_registry.VideoRegistryError):
            video_registry.write_registry(
                "_template",
                "bad",
                internal,
                root=self.root,
            )

    def test_resolve_raw_dir(self) -> None:
        from avo.session import normalize_path

        raw = _external_raw("demo-two")
        video_registry.write_registry("_template", "demo-two", raw, root=self.root)
        resolved = video_registry.resolve_raw_dir("_template", "demo-two", root=self.root)
        self.assertEqual(normalize_path(resolved), normalize_path(raw))

    def test_rebuild_index(self) -> None:
        video_registry.write_registry(
            "_template",
            "indexed",
            _external_raw("indexed"),
            root=self.root,
        )
        index_path = video_registry.rebuild_index("_template", root=self.root)
        self.assertTrue(index_path.is_file())
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["videos"]), 1)


class InitProjectRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / "external-footage"
        self.raw.mkdir()
        self.provider_dir = self.root / "providers" / "_template"
        self.provider_dir.mkdir(parents=True)
        (self.provider_dir / "avo.provider.json").write_text(
            json.dumps(
                {
                    "name": "_template",
                    "kind": "youtube",
                    "media": {"rawRoot": str(self.raw.parent)},
                    "assets": {"logos": "providers/_template/logo"},
                    "transcription": {"language": "en"},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_project_writes_registry_with_video_id(self) -> None:
        import avo.init_project as ip

        original_providers = ip.providers_dir
        ip.providers_dir = lambda root=None: self.root / "providers"  # type: ignore[assignment]
        try:
            with mock.patch.object(ip, "repo_root", return_value=self.root):
                code = ip.main(
                    [
                        "--provider",
                        "_template",
                        "--raw-dir",
                        str(self.raw),
                        "--video-id",
                        "my-video",
                        "--yes",
                    ]
                )
        finally:
            ip.providers_dir = original_providers  # type: ignore[assignment]

        self.assertEqual(code, 0)
        self.assertTrue((self.raw / "avo.project.json").is_file())
        self.assertTrue(
            (self.root / "providers" / "_template" / "videos" / "my-video" / "video.json").is_file()
        )


class StatsFilterTests(unittest.TestCase):
    def test_filter_sessions_by_raw_dir(self) -> None:
        sessions = [
            {"provider": "a", "rawDir": "H:/one", "bytes": {"freed": 10, "preserved": 5}},
            {"provider": "a", "rawDir": "H:/two", "bytes": {"freed": 20, "preserved": 5}},
        ]
        filtered = stats._filter_sessions(sessions, raw_dir="H:/one")
        self.assertEqual(len(filtered), 1)
        totals = stats._totals_for_sessions(filtered)
        self.assertEqual(totals["videosCompleted"], 1)


if __name__ == "__main__":
    unittest.main()
