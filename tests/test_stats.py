"""Tests for helpers/stats.py — record, totals, rotation, display."""

from __future__ import annotations

import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER = "20260801-demo-master-v001"

sys.path.insert(0, str(HELPERS))

import avo_state  # noqa: E402
import stats  # noqa: E402


def _sample_session(session_id: str = "sess-1", *, freed: int = 1000) -> dict:
    return {
        "id": session_id,
        "provider": "bishop",
        "rawDir": str(FIXTURE),
        "title": "Demo",
        "masterBasename": MASTER,
        "completedAt": "2026-08-01T12:00:00Z",
        "bytes": {"preCleanupProject": 5000, "freed": freed, "preserved": 2000},
        "files": {"deletedCount": 3, "preservedCount": 5, "deletedSample": ["edit/preview/x.mp4"]},
        "estimatedMinutesSaved": 30,
        "estimationModel": stats.ESTIMATION_MODEL,
    }


class StatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_root = Path(self._tmpdir.name)
        self.repo_patcher = mock.patch.object(avo_state, "repo_root", return_value=self.state_root)
        self.repo_patcher.start()
        self.addCleanup(self.repo_patcher.stop)
        avo_state.state_dir().mkdir(parents=True, exist_ok=True)

    def test_estimate_time_saved(self) -> None:
        self.assertEqual(stats.estimate_time_saved(120.0, 2.5), 5)
        self.assertIsNone(stats.estimate_time_saved(None, 2.5))
        self.assertIsNone(stats.estimate_time_saved(0, 2.5))

    def test_load_stats_config_defaults(self) -> None:
        cfg = stats.load_stats_config()
        self.assertEqual(cfg.time_saved_edit_factor, 2.5)
        self.assertEqual(cfg.session_retention, 200)
        self.assertEqual(cfg.deleted_path_sample_limit, 50)

    def test_record_session_updates_totals(self) -> None:
        stats.record_session(_sample_session())
        state = avo_state.load_state()
        totals = state["stats"]["totals"]
        self.assertEqual(totals["videosCompleted"], 1)
        self.assertEqual(totals["bytesFreed"], 1000)
        self.assertEqual(totals["preservedBytes"], 2000)
        self.assertEqual(totals["estimatedMinutesSaved"], 30)

    def test_record_session_idempotent_no_double_count(self) -> None:
        stats.record_session(_sample_session(freed=1000))
        stats.record_session(_sample_session(freed=1500))
        state = avo_state.load_state()
        totals = state["stats"]["totals"]
        self.assertEqual(totals["videosCompleted"], 1)
        self.assertEqual(totals["bytesFreed"], 1500)
        self.assertEqual(len(state["stats"]["sessions"]), 1)

    def test_rotation_preserves_totals(self) -> None:
        with mock.patch.object(
            stats,
            "load_stats_config",
            return_value=stats.StatsConfig(session_retention=3),
        ):
            for i in range(5):
                session = _sample_session(f"sess-{i}", freed=100 * (i + 1))
                session["completedAt"] = f"2026-08-0{i + 1}T12:00:00Z"
                stats.record_session(session)

        state = avo_state.load_state()
        self.assertEqual(len(state["stats"]["sessions"]), 3)
        self.assertEqual(state["stats"]["totals"]["videosCompleted"], 5)
        self.assertEqual(
            state["stats"]["totals"]["bytesFreed"],
            sum(100 * (i + 1) for i in range(5)),
        )

    def test_format_human_includes_estimated_disclaimer(self) -> None:
        stats.record_session(_sample_session())
        display = stats.compute_display_metrics()
        text = stats.format_human(display)
        self.assertIn("estimated", text.lower())
        self.assertIn("Videos completed:", text)

    def test_show_zero_sessions_friendly_message(self) -> None:
        display = stats.compute_display_metrics()
        text = stats.format_human(display)
        self.assertIn("No completed videos", text)

    def test_show_json_emits_avo_json_stderr(self) -> None:
        stats.record_session(_sample_session())
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            code = stats.main(["show", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(any(line.startswith("AVO_JSON ") for line in err.getvalue().splitlines()))

    def test_session_from_wrap_probes_durations(self) -> None:
        wrap_payload = {
            "schemaVersion": 1,
            "status": "final",
            "sessionId": "wrap-sess",
            "rawDir": str(FIXTURE.resolve()),
            "provider": "bishop",
            "title": "Fixture",
            "masterBasename": MASTER,
            "generatedAt": "2026-08-01T23:00:00Z",
            "space": {
                "preCleanupProjectBytes": 1000,
                "deleteCandidateBytes": 500,
                "preservedBytes": 500,
                "freedBytes": 500,
            },
            "files": {
                "deletedCount": 2,
                "preserved": [{"path": "edit/masters/x.mp4", "bytes": 400}],
                "deletedSample": ["edit/preview/a.mp4"],
            },
        }

        def fake_duration(path: Path) -> float | None:
            if path.name == "source.mp4":
                return 120.0
            if path.name.endswith(".mp4") and "masters" in path.as_posix():
                return 90.0
            return None

        with mock.patch.object(stats, "media_duration", fake_duration):
            session_payload = stats.session_from_wrap(wrap_payload)
        self.assertEqual(session_payload["sourceDurationSeconds"], 120.0)
        self.assertEqual(session_payload["masterDurationSeconds"], 90.0)
        self.assertEqual(session_payload["estimatedMinutesSaved"], 5)

    def test_session_from_wrap_null_duration_when_probe_fails(self) -> None:
        wrap_payload = {
            "schemaVersion": 1,
            "status": "final",
            "sessionId": "wrap-sess",
            "rawDir": str(FIXTURE.resolve()),
            "provider": "bishop",
            "masterBasename": MASTER,
            "generatedAt": "2026-08-01T23:00:00Z",
            "space": {"freedBytes": 0, "preservedBytes": 0, "preCleanupProjectBytes": 0},
            "files": {"deletedCount": 0, "preserved": [], "deletedSample": []},
        }
        with mock.patch.object(stats, "media_duration", lambda _p: None):
            session_payload = stats.session_from_wrap(wrap_payload)
        self.assertIsNone(session_payload["sourceDurationSeconds"])
        self.assertIsNone(session_payload["estimatedMinutesSaved"])

    def test_verbose_display_includes_tier_b_c(self) -> None:
        session = _sample_session()
        session["sourceDurationSeconds"] = 100.0
        session["masterDurationSeconds"] = 80.0
        session["phases"] = ["transcribe", "cut"]
        session["approvalGates"] = ["rough"]
        stats.record_session(session)
        display = stats.compute_display_metrics(verbose=True)
        text = stats.format_human(display, verbose=True)
        self.assertIn("Tier B", text)
        self.assertIn("Tier C", text)


if __name__ == "__main__":
    unittest.main()
