"""Unit tests for scripts/ci/check_npm_audit.py (task-011 / FR-6)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "check_npm_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_npm_audit", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestCheckNpmAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_high_advisory_ids_extracts_ghsa(self) -> None:
        audit = {
            "vulnerabilities": {
                "brace-expansion": {
                    "severity": "high",
                    "via": [
                        {
                            "severity": "high",
                            "url": "https://github.com/advisories/GHSA-mh99-v99m-4gvg",
                        }
                    ],
                    "nodes": ["node_modules/brace-expansion"],
                }
            }
        }
        found = self.mod._high_advisory_ids(audit)
        self.assertIn("GHSA-MH99-V99M-4GVG", found)
        self.assertEqual(found["GHSA-MH99-V99M-4GVG"]["package"], "brace-expansion")

    def test_moderate_only_is_ignored(self) -> None:
        audit = {
            "vulnerabilities": {
                "tar": {
                    "severity": "moderate",
                    "via": [
                        {
                            "severity": "moderate",
                            "url": "https://github.com/advisories/GHSA-r292-9mhp-454m",
                        }
                    ],
                }
            }
        }
        self.assertEqual(self.mod._high_advisory_ids(audit), {})

    def test_main_fails_on_unexpected_high(self) -> None:
        audit = {
            "vulnerabilities": {
                "ip-address": {
                    "severity": "high",
                    "via": [
                        {
                            "severity": "high",
                            "url": "https://github.com/advisories/GHSA-mwp4-54f8-5fhr",
                        }
                    ],
                    "nodes": ["node_modules/ip-address"],
                }
            }
        }
        with (
            mock.patch.object(self.mod, "_load_allowlist", return_value={}),
            mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
        ):
            self.assertEqual(self.mod.main(), 1)

    def test_main_passes_when_allowlisted(self) -> None:
        audit = {
            "vulnerabilities": {
                "ip-address": {
                    "severity": "high",
                    "via": [
                        {
                            "severity": "high",
                            "url": "https://github.com/advisories/GHSA-mwp4-54f8-5fhr",
                        }
                    ],
                    "nodes": ["node_modules/ip-address"],
                }
            }
        }
        allow = {
            "GHSA-MWP4-54F8-5FHR": {
                "id": "GHSA-mwp4-54f8-5fhr",
                "package": "ip-address",
                "reason": "documented test exception",
                "expires": "2099-01-01",
            }
        }
        with (
            mock.patch.object(self.mod, "_load_allowlist", return_value=allow),
            mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
        ):
            self.assertEqual(self.mod.main(), 0)

    def test_main_fails_on_unused_allowlist_entry(self) -> None:
        allow = {
            "GHSA-MWP4-54F8-5FHR": {
                "id": "GHSA-mwp4-54f8-5fhr",
                "package": "ip-address",
                "reason": "stale",
                "expires": "2099-01-01",
            }
        }
        with (
            mock.patch.object(self.mod, "_load_allowlist", return_value=allow),
            mock.patch.object(
                self.mod, "_run_npm_audit", return_value={"vulnerabilities": {}}
            ),
        ):
            self.assertEqual(self.mod.main(), 1)

    def test_no_ghsa_records_package_and_via_then_fails(self) -> None:
        audit = {
            "vulnerabilities": {
                "@jscpd/finder": {
                    "severity": "high",
                    "via": ["fast-glob"],
                    "nodes": ["node_modules/@jscpd/finder"],
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deps-findings.json"
            stderr = io.StringIO()
            with (
                mock.patch.object(self.mod, "FINDINGS_PATH", path),
                mock.patch.object(self.mod, "_load_allowlist", return_value={}),
                mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
                contextlib.redirect_stderr(stderr),
            ):
                code = self.mod.main()
            payload = json.loads(path.read_text(encoding="utf-8"))
        output = stderr.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("without GHSA id", output)
        self.assertIn("package=@jscpd/finder via='fast-glob'", output)
        self.assertEqual(
            payload["findings"],
            [{"package": "@jscpd/finder", "id": None, "via": "fast-glob"}],
        )
        allow = json.loads(
            (ROOT / "scripts/ci/deps-audit-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertEqual(allow["npm"]["advisory_ids"], [])

    def test_two_unwaived_findings_are_reported_and_exit_1(self) -> None:
        """Collect every hit before exiting. Dev paths are not exempt."""
        audit = {
            "vulnerabilities": {
                "@jscpd/finder": {
                    "severity": "high",
                    "dev": True,
                    "via": ["fast-glob"],
                    "nodes": ["node_modules/@jscpd/finder"],
                },
                "minimatch": {
                    "severity": "critical",
                    "via": ["brace-expansion"],
                    "nodes": ["node_modules/minimatch"],
                },
                "tar": {
                    "severity": "moderate",
                    "dev": True,
                    "via": ["other"],
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deps-findings.json"
            stderr = io.StringIO()
            with (
                mock.patch.object(self.mod, "FINDINGS_PATH", path),
                mock.patch.object(self.mod, "_load_allowlist", return_value={}),
                mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
                contextlib.redirect_stderr(stderr),
            ):
                code = self.mod.main()
            payload = json.loads(path.read_text(encoding="utf-8"))
        output = stderr.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("package=@jscpd/finder via='fast-glob'", output)
        self.assertIn("package=minimatch via='brace-expansion'", output)
        self.assertNotIn("tar", output)
        self.assertEqual(
            payload["findings"],
            [
                {"package": "@jscpd/finder", "id": None, "via": "fast-glob"},
                {"package": "minimatch", "id": None, "via": "brace-expansion"},
            ],
        )

    def test_no_ghsa_id_is_not_waived_by_another_allowlisted_hit(self) -> None:
        audit = {
            "vulnerabilities": {
                "ip-address": {
                    "severity": "high",
                    "via": [
                        {
                            "severity": "high",
                            "name": "ip-address",
                            "url": "https://github.com/advisories/GHSA-mwp4-54f8-5fhr",
                        }
                    ],
                    "nodes": ["node_modules/ip-address"],
                },
                "@jscpd/finder": {
                    "severity": "high",
                    "dev": True,
                    "via": ["fast-glob"],
                    "nodes": ["node_modules/@jscpd/finder"],
                },
            }
        }
        allow = {
            "GHSA-MWP4-54F8-5FHR": {
                "id": "GHSA-mwp4-54f8-5fhr",
                "package": "ip-address",
                "reason": "documented test exception",
                "expires": "2099-01-01",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deps-findings.json"
            stderr = io.StringIO()
            with (
                mock.patch.object(self.mod, "FINDINGS_PATH", path),
                mock.patch.object(self.mod, "_load_allowlist", return_value=allow),
                mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
                contextlib.redirect_stderr(stderr),
            ):
                code = self.mod.main()
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertIn("package=@jscpd/finder via='fast-glob'", stderr.getvalue())
        self.assertEqual(
            payload["findings"],
            [{"package": "@jscpd/finder", "id": None, "via": "fast-glob"}],
        )

    def test_npm_audit_command_keeps_dev_dependencies(self) -> None:
        completed = mock.Mock(returncode=0, stdout='{"vulnerabilities":{}}', stderr="")
        with (
            mock.patch.object(self.mod.shutil, "which", return_value="npm"),
            mock.patch.object(
                self.mod.subprocess, "run", return_value=completed
            ) as run,
        ):
            self.mod._run_npm_audit()
        argv = run.call_args.args[0]
        self.assertEqual(argv[1:], ["audit", "--json"])
        self.assertNotIn("--omit=dev", argv)
        self.assertNotIn("--production", argv)

    def test_record_pip_keeps_pysec_id(self) -> None:
        payload = {
            "dependencies": [
                {
                    "name": "requests",
                    "version": "2.0.0",
                    "vulns": [{"id": "PYSEC-2024-123", "fix_versions": []}],
                },
                {"name": "local", "skip_reason": "skip-editable"},
            ],
            "fixes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deps-findings.json"
            with mock.patch.object(self.mod, "FINDINGS_PATH", path):
                code = self.mod.record_pip_payload(payload)
            written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(
            written["findings"],
            [{"package": "requests", "id": "PYSEC-2024-123", "via": ""}],
        )

    def test_allowlist_file_schema(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/deps-audit-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertIn("npm", raw)
        self.assertIn("pip", raw)
        self.assertIsInstance(raw["npm"]["advisory_ids"], list)
        self.assertIsInstance(raw["pip"]["ignore_vulns"], list)


if __name__ == "__main__":
    unittest.main()
