"""Unit tests for scripts/ci/check_npm_audit.py (task-011 / FR-6)."""

from __future__ import annotations

import importlib.util
import json
import sys
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
            mock.patch.object(self.mod, "_run_npm_audit", return_value={"vulnerabilities": {}}),
        ):
            self.assertEqual(self.mod.main(), 1)

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
