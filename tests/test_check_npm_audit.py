"""Unit tests for scripts/ci/check_npm_audit.py (task-011 / FR-6)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "check_npm_audit.py"

BRACES_GHSA = "GHSA-vfj7-8cjw-p6xm"
BRACES_URL = f"https://github.com/advisories/{BRACES_GHSA}"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_npm_audit", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _braces_chain() -> dict:
    """Parents name the next package. The GHSA sits on braces."""
    return {
        "vulnerabilities": {
            "@semantic-release/changelog": {
                "severity": "high",
                "via": ["semantic-release"],
                "nodes": ["node_modules/@semantic-release/changelog"],
            },
            "semantic-release": {
                "severity": "high",
                "via": ["micromatch"],
                "nodes": ["node_modules/semantic-release"],
            },
            "micromatch": {
                "severity": "high",
                "via": ["braces"],
                "nodes": ["node_modules/micromatch"],
            },
            "braces": {
                "severity": "high",
                "via": [
                    {
                        "severity": "high",
                        "name": "braces",
                        "url": BRACES_URL,
                        "range": "<=3.0.3",
                    }
                ],
                "nodes": ["node_modules/braces"],
            },
        }
    }


class TestCheckNpmAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def _run(
        self,
        audit: dict,
        allow: dict | None = None,
        lock: dict | None = None,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(self.mod, "_load_allowlist", return_value=allow or {}),
            mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
            mock.patch.object(self.mod, "_lock_packages", return_value=lock or {}),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = self.mod.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_critical_fails(self) -> None:
        direct = {
            "vulnerabilities": {
                "left-pad": {
                    "severity": "critical",
                    "via": [
                        {
                            "severity": "critical",
                            "url": "https://github.com/advisories/GHSA-mwp4-54f8-5fhr",
                        }
                    ],
                    "nodes": ["node_modules/left-pad"],
                }
            }
        }
        code, out, err = self._run(direct)
        self.assertEqual(code, 1)
        self.assertIn("GHSA-mwp4-54f8-5fhr", err)
        self.assertIn("FAIL, 1 critical, 0 high reported", out)

        chained = {
            "vulnerabilities": {
                "wrapper": {
                    "severity": "critical",
                    "via": ["braces"],
                    "nodes": ["node_modules/wrapper"],
                },
                "braces": _braces_chain()["vulnerabilities"]["braces"],
            }
        }
        lock = {"node_modules/braces": {"version": "3.0.3"}}
        code, out, err = self._run(chained, lock=lock)
        self.assertEqual(code, 1)
        self.assertIn(f"braces@3.0.3 {BRACES_GHSA}", err)
        self.assertNotIn("without GHSA id", err)
        self.assertIn("FAIL, 1 critical, 1 high reported", out)

    def test_critical_without_ghsa_fails(self) -> None:
        audit = {
            "vulnerabilities": {
                "left-pad": {
                    "severity": "critical",
                    "via": [{"severity": "critical", "source": 1, "title": "no id"}],
                }
            }
        }
        with (
            mock.patch.object(self.mod, "_load_allowlist", return_value={}),
            mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
            mock.patch.object(self.mod, "_lock_packages", return_value={}),
        ):
            with self.assertRaises(SystemExit) as raised:
                self.mod.main()
        self.assertIn("without GHSA id", str(raised.exception))

    def test_highs_pass_but_are_reported(self) -> None:
        lock = {"node_modules/braces": {"version": "3.0.3"}}
        code, out, err = self._run(_braces_chain(), lock=lock)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn(f"braces@3.0.3 {BRACES_GHSA}", out)
        self.assertIn("@semantic-release/changelog", out)
        self.assertIn("PASS, 0 critical, 4 high reported", out)
        self.assertNotIn("without GHSA id", out)
        summary = json.loads(self.mod.SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(summary["ok"], True)
        self.assertEqual(summary["critical"], 0)
        self.assertEqual(summary["high"], 4)

    def test_cycle_via_names_root_advisory(self) -> None:
        braces = _braces_chain()["vulnerabilities"]["braces"]
        audit = {
            "vulnerabilities": {
                "semantic-release": {
                    "severity": "high",
                    "via": ["@semantic-release/github", "micromatch"],
                    "nodes": ["node_modules/semantic-release"],
                },
                "@semantic-release/github": {
                    "severity": "high",
                    "via": ["semantic-release"],
                    "nodes": ["node_modules/@semantic-release/github"],
                },
                "@semantic-release/release-notes-generator": {
                    "severity": "high",
                    "via": ["semantic-release"],
                    "nodes": ["node_modules/@semantic-release/release-notes-generator"],
                },
                "micromatch": {
                    "severity": "high",
                    "via": ["braces"],
                    "nodes": ["node_modules/micromatch"],
                },
                "braces": braces,
            }
        }
        lock = {"node_modules/braces": {"version": "3.0.3"}}
        code, out, err = self._run(audit, lock=lock)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertNotIn("(no GHSA id)", out)
        self.assertIn(
            f"high @semantic-release/github via braces@3.0.3 {BRACES_GHSA}",
            out,
        )
        self.assertIn(
            "high @semantic-release/release-notes-generator via "
            f"braces@3.0.3 {BRACES_GHSA}",
            out,
        )
        self.assertIn("PASS, 0 critical, 5 high reported", out)

    def test_critical_cycle_without_ghsa_fails(self) -> None:
        audit = {
            "vulnerabilities": {
                "alpha": {"severity": "critical", "via": ["beta"]},
                "beta": {"severity": "critical", "via": ["alpha"]},
            }
        }
        with (
            mock.patch.object(self.mod, "_load_allowlist", return_value={}),
            mock.patch.object(self.mod, "_run_npm_audit", return_value=audit),
            mock.patch.object(self.mod, "_lock_packages", return_value={}),
        ):
            with self.assertRaises(SystemExit) as raised:
                self.mod.main()
        self.assertIn("without GHSA id", str(raised.exception))

    def test_moderate_is_reported_and_passes(self) -> None:
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
        code, out, _err = self._run(audit)
        self.assertEqual(code, 0)
        self.assertIn("GHSA-r292-9mhp-454m", out)
        self.assertIn("PASS, 0 critical, 0 high reported", out)

    def test_main_passes_when_critical_allowlisted(self) -> None:
        audit = {
            "vulnerabilities": {
                "left-pad": {
                    "severity": "critical",
                    "via": [
                        {
                            "severity": "critical",
                            "url": "https://github.com/advisories/GHSA-mwp4-54f8-5fhr",
                        }
                    ],
                    "nodes": ["node_modules/left-pad"],
                }
            }
        }
        allow = {
            "GHSA-MWP4-54F8-5FHR": {
                "id": "GHSA-mwp4-54f8-5fhr",
                "package": "left-pad",
                "reason": "documented test exception",
                "expires": "2099-01-01",
            }
        }
        code, out, err = self._run(audit, allow=allow)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("documented test exception", out)
        self.assertIn("PASS, 1 critical, 0 high reported", out)

    def test_main_fails_on_unused_allowlist_entry(self) -> None:
        allow = {
            "GHSA-MWP4-54F8-5FHR": {
                "id": "GHSA-mwp4-54f8-5fhr",
                "package": "left-pad",
                "reason": "stale",
                "expires": "2099-01-01",
            }
        }
        code, _out, err = self._run({"vulnerabilities": {}}, allow=allow)
        self.assertEqual(code, 1)
        self.assertIn("unused npm audit allowlist", err)

    def test_missing_or_invalid_audit_json_fails(self) -> None:
        cases = ("", "not-json{")
        for stdout in cases:
            proc = mock.Mock(returncode=1, stdout=stdout, stderr="")
            with (
                mock.patch.object(self.mod.subprocess, "run", return_value=proc),
                mock.patch.object(self.mod, "_npm_executable", return_value="npm"),
                self.assertRaises(SystemExit) as raised,
            ):
                self.mod.main()
            self.assertNotEqual(raised.exception.code, 0)
            message = str(raised.exception)
            self.assertTrue(
                "no JSON" in message or "JSON parse failed" in message,
                msg=message,
            )

    def test_allowlist_file_schema(self) -> None:
        raw = json.loads(
            (ROOT / "scripts/ci/deps-audit-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertIn("npm", raw)
        self.assertIn("pip", raw)
        self.assertIsInstance(raw["npm"]["advisory_ids"], list)
        self.assertIsInstance(raw["pip"]["ignore_vulns"], list)
        self.assertEqual(raw["npm"]["advisory_ids"], [])
        self.assertEqual(raw["pip"]["ignore_vulns"], [])


if __name__ == "__main__":
    unittest.main()
