from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import pytest

from avo import validate_dependencies as gate

ROOT = Path(__file__).resolve().parents[1]


class ValidateDependenciesManifestTests(unittest.TestCase):
    def test_manifest_required_tools(self) -> None:
        data = json.loads(
            (ROOT / "config" / "avo.dependencies.json").read_text(encoding="utf-8")
        )
        tools = data["tools"]
        self.assertEqual(
            tools["watch-skill"]["repo"], "https://github.com/oxbshw/watch-skill"
        )
        self.assertEqual(tools["watch-skill"]["path"], "tools/watch-skill")

    def test_routing_alignment(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import (
            load_manifest,
            load_routing,
            routing_covers_manifest,
        )

        manifest = load_manifest(ROOT)
        routing = load_routing(ROOT)
        missing = routing_covers_manifest(routing, manifest)
        self.assertEqual(missing, [])

    def test_python_project_check(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import check_python_project

        result = check_python_project(
            ROOT,
            "avo-engine",
            {
                "manifest": "pyproject.toml",
                "helpers": ["src/avo/transcribe.py"],
            },
        )
        self.assertEqual(result.status, "OK")

    def test_avo_engine_has_legacy_alias(self) -> None:
        data = json.loads(
            (ROOT / "config" / "avo.dependencies.json").read_text(encoding="utf-8")
        )
        engine = data["tools"]["avo-engine"]
        self.assertIn("video-use-engine", engine.get("aliases", []))

    def test_deprecated_alias_tool_skipped_with_warn(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import iter_canonical_tools

        tools = {
            "avo-engine": {"aliases": ["video-use-engine"], "kind": "python-project"},
            "video-use-engine": {"kind": "python-project"},
        }
        canonical, warnings = iter_canonical_tools(tools)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0][0], "avo-engine")
        self.assertTrue(any(w.tool == "video-use-engine" for w in warnings))

    @mock.patch("avo.validate_dependencies.repo_reachable", return_value=True)
    @mock.patch("avo.validate_dependencies.shallow_clone", return_value=True)
    def test_watch_skill_shallow_clone_ci(
        self, _clone: mock.Mock, _reachable: mock.Mock
    ) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import check_git_clone

        spec = {
            "repo": "https://github.com/oxbshw/watch-skill",
            "path": "tools/watch-skill-ci-test-mock",
            "ciPolicy": "shallow-clone-if-missing",
        }
        result = check_git_clone(ROOT, "watch-skill", spec, ci=True)
        self.assertIn(result.status, ("OK", "WARN"))


class OptionalToolHealthTests(unittest.TestCase):
    @mock.patch("avo.validate_dependencies._probe_ai_memory_server", return_value=False)
    @mock.patch("avo.validate_dependencies.shutil.which", return_value=None)
    @mock.patch("avo.validate_dependencies.check_git_clone")
    def test_ai_memory_optional_warns_without_server(
        self, clone: mock.Mock, _which: mock.Mock, _probe: mock.Mock
    ) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import CheckResult, check_ai_memory_optional

        clone.return_value = CheckResult(
            "ai-memory", "OK", "present at tools/ai-memory"
        )
        result = check_ai_memory_optional(
            ROOT,
            "ai-memory",
            {"path": "tools/ai-memory", "repo": "https://example.com/ai-memory"},
            ci=False,
        )
        self.assertEqual(result.status, "WARN")
        self.assertIn("server not running", result.note)

    @mock.patch("avo.validate_dependencies.shutil.which")
    def test_ai_jail_linux_warns_without_bwrap(self, which: mock.Mock) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import check_ai_jail_optional

        def _which(name: str):
            return "/usr/bin/ai-jail" if name == "ai-jail" else None

        which.side_effect = _which
        with mock.patch("platform.system", return_value="Linux"):
            result = check_ai_jail_optional(
                ROOT,
                "ai-jail",
                {"binary": "ai-jail", "path": "tools/ai-jail"},
                ci=False,
            )
        self.assertEqual(result.status, "WARN")
        self.assertIn("bwrap", result.note)


if __name__ == "__main__":
    unittest.main()


def test_manifest_and_routing_preserve_unicode_and_validate_shape(tmp_path):
    manifest = tmp_path / "avo.dependencies.json"
    manifest.write_text('{"tools": {}, "name": "câmera"}', encoding="utf-8")
    routing = tmp_path / "avo.config.json"
    routing.write_text('{"jobs": {"edição": {}}}', encoding="utf-8")
    assert gate.load_manifest(tmp_path) == {"tools": {}, "name": "câmera"}
    assert gate.load_routing(tmp_path) == {"jobs": {"edição": {}}}
    for invalid in ({}, {"tools": []}, {"tools": None}):
        manifest.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError, match="must contain a tools object"):
            gate.load_manifest(tmp_path)
    manifest.unlink()
    routing.unlink()
    with pytest.raises(FileNotFoundError, match="missing dependency manifest"):
        gate.load_manifest(tmp_path)
    with pytest.raises(FileNotFoundError, match="missing routing config"):
        gate.load_routing(tmp_path)


def test_aliases_keep_canonical_order_and_exact_remediation():
    engine = {"aliases": ["legacy"], "job": "render"}
    tools = {
        "engine": engine,
        "legacy": {"job": "obsolete"},
        "optional": {"aliases": None, "job": "captions"},
        "manual": {},
    }
    assert gate.build_alias_index(tools) == {"legacy": "engine"}
    canonical, warnings = gate.iter_canonical_tools(tools)
    assert canonical == [
        ("engine", engine),
        ("optional", tools["optional"]),
        ("manual", {}),
    ]
    assert warnings == [
        gate.CheckResult(
            "legacy",
            "WARN",
            "deprecated alias for engine — use engine in avo.dependencies.json",
        )
    ]
    assert gate.routing_covers_manifest({}, {"tools": tools}) == [
        "engine -> job 'render'",
        "optional -> job 'captions'",
    ]
    assert gate.routing_covers_manifest({"jobs": {"render": {}}}, {"tools": tools}) == [
        "optional -> job 'captions'"
    ]
    assert gate.routing_covers_manifest({"jobs": None}, {"tools": None}) == []


def test_python_project_requires_files_and_checks_every_declared_helper(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(gate.sys, "frozen", False, raising=False)
    assert gate.check_python_project(tmp_path, "native", {}) == gate.CheckResult(
        "native", "FAIL", "missing pyproject.toml"
    )
    (tmp_path / "custom.toml").write_text("[project]", encoding="utf-8")
    spec = {"manifest": "custom.toml", "helpers": ["first.py", "second.py"]}
    (tmp_path / "first.py").write_text("", encoding="utf-8")
    (tmp_path / "second.py").mkdir()
    assert gate.check_python_project(tmp_path, "native", spec) == gate.CheckResult(
        "native", "FAIL", "missing helper second.py"
    )
    (tmp_path / "second.py").rmdir()
    (tmp_path / "second.py").write_text("", encoding="utf-8")
    assert gate.check_python_project(tmp_path, "native", spec) == gate.CheckResult(
        "native", "OK", "custom.toml + engine modules present"
    )
    monkeypatch.setattr(gate.sys, "frozen", True)
    assert gate.check_python_project(tmp_path, "native", {"manifest": "absent"}) == (
        gate.CheckResult("native", "OK", "frozen engine (clone helpers not required)")
    )


@pytest.mark.parametrize(
    "ci,required,reachable,policy,cloned,status,note",
    [
        (
            False,
            True,
            False,
            None,
            False,
            "FAIL",
            "repo unreachable: https://example.com/tool",
        ),
        (
            True,
            False,
            False,
            "shallow-clone-if-missing",
            False,
            "WARN",
            "repo unreachable offline: https://example.com/tool",
        ),
        (
            True,
            True,
            False,
            "other",
            False,
            "FAIL",
            "repo unreachable: https://example.com/tool",
        ),
        (
            True,
            True,
            True,
            "shallow-clone-if-missing",
            True,
            "OK",
            "shallow-cloned to tools/fixture",
        ),
        (
            True,
            True,
            True,
            "shallow-clone-if-missing",
            False,
            "WARN",
            "clone failed (offline?): tools/fixture",
        ),
        (
            False,
            True,
            True,
            "shallow-clone-if-missing",
            False,
            "FAIL",
            "missing clone at tools/fixture — run setup or git clone https://example.com/tool",
        ),
        (
            True,
            False,
            True,
            None,
            False,
            "WARN",
            "missing clone at tools/fixture — run setup or git clone https://example.com/tool",
        ),
    ],
)
def test_clone_readiness_distinguishes_offline_policy_and_failed_install(
    tmp_path, monkeypatch, ci, required, reachable, policy, cloned, status, note
):
    reach = mock.Mock(return_value=reachable)
    clone = mock.Mock(return_value=cloned)
    monkeypatch.setattr(gate, "repo_reachable", reach)
    monkeypatch.setattr(gate, "shallow_clone", clone)
    spec = {
        "path": "tools/fixture",
        "repo": "https://example.com/tool",
        "required": required,
    }
    if policy is not None:
        spec["ciPolicy"] = policy
    assert gate.check_git_clone(tmp_path, "fixture", spec, ci=ci) == gate.CheckResult(
        "fixture", status, note
    )
    reach.assert_called_once_with(spec["repo"])
    if reachable and ci and policy == "shallow-clone-if-missing":
        clone.assert_called_once_with(spec["repo"], tmp_path / "tools/fixture")
    else:
        clone.assert_not_called()


def test_existing_clone_never_fetches_and_empty_clone_requires_repo(
    tmp_path, monkeypatch
):
    reach = mock.Mock(side_effect=AssertionError("unexpected network request"))
    monkeypatch.setattr(gate, "repo_reachable", reach)
    target = tmp_path / "tools/fixture"
    target.mkdir(parents=True)
    spec = {"path": "tools/fixture"}
    assert gate.check_git_clone(tmp_path, "fixture", spec, ci=True) == gate.CheckResult(
        "fixture", "FAIL", "no repo URL in manifest"
    )
    (target / "README").write_text("installed", encoding="utf-8")
    assert gate.check_git_clone(tmp_path, "fixture", spec, ci=True) == gate.CheckResult(
        "fixture", "OK", "present at tools/fixture"
    )
    reach.assert_not_called()


@pytest.mark.parametrize(
    "on_path,server_up", [(False, False), (False, True), (True, False), (True, True)]
)
@pytest.mark.parametrize("clone_status", ["OK", "FAIL"])
def test_memory_readiness_reports_binary_server_and_clone_independently(
    tmp_path, monkeypatch, on_path, server_up, clone_status
):
    base = gate.CheckResult("memory", clone_status, "clone diagnostic")
    clone = mock.Mock(return_value=base)
    which = mock.Mock(return_value="/bin/ai-memory" if on_path else None)
    probe = mock.Mock(return_value=server_up)
    monkeypatch.setattr(gate, "check_git_clone", clone)
    monkeypatch.setattr(gate.shutil, "which", which)
    monkeypatch.setattr(gate, "_probe_ai_memory_server", probe)
    spec = {"path": "tools/memory"}
    result = gate.check_ai_memory_optional(tmp_path, "memory", spec, ci=True)
    doc = "see docs/ai-memory-and-ai-jail.md"
    expected = {
        (True, True): ("OK", "ai-memory on PATH; server reachable"),
        (True, False): ("WARN", f"ai-memory on PATH; server not detected ({doc})"),
        (False, True): ("OK", "clone diagnostic; server reachable"),
        (False, False): ("WARN", f"clone diagnostic; server not running ({doc})"),
    }
    if not on_path and clone_status != "OK":
        assert result is base
    else:
        assert result == gate.CheckResult("memory", *expected[on_path, server_up])
    clone.assert_called_once_with(tmp_path, "memory", spec, ci=True)
    which.assert_called_once_with("ai-memory")
    probe.assert_called_once_with()


@pytest.mark.parametrize(
    "platform,binary,bwrap,status,note",
    [
        ("Linux", True, True, "OK", "custom-jail on PATH"),
        ("Linux", True, False, "WARN", "custom-jail on PATH; bwrap missing on PATH"),
        ("Darwin", True, False, "OK", "custom-jail on PATH"),
    ],
)
def test_native_jail_readiness_keeps_platform_requirements(
    tmp_path, monkeypatch, platform, binary, bwrap, status, note
):
    monkeypatch.setattr("platform.system", lambda: platform)
    monkeypatch.setattr(
        gate.shutil,
        "which",
        lambda name: name if (binary if name == "custom-jail" else bwrap) else None,
    )
    assert gate.check_ai_jail_optional(
        tmp_path, "jail", {"binary": "custom-jail"}, ci=False
    ) == gate.CheckResult("jail", status, note)


@pytest.mark.parametrize("version", ["build one\nrelease two", ""])
@pytest.mark.parametrize("bwrap_code", [0, 1])
def test_windows_jail_checks_wsl_binary_and_bubblewrap(
    tmp_path, monkeypatch, version, bwrap_code
):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(gate.shutil, "which", lambda _: None)
    wsl = mock.Mock(side_effect=[(0, version), (bwrap_code, "")])
    monkeypatch.setattr(gate, "_wsl_bash", wsl)
    result = gate.check_ai_jail_optional(tmp_path, "jail", {}, ci=True)
    if bwrap_code:
        expected = (
            "WARN",
            "ai-jail in WSL; bwrap missing — sudo apt install bubblewrap",
        )
    else:
        expected = (
            "OK",
            f"ai-jail in WSL ({'release two' if version else 'verified in WSL'})",
        )
    assert result == gate.CheckResult("jail", *expected)
    assert wsl.call_args_list == [
        mock.call("command -v ai-jail >/dev/null && ai-jail --version"),
        mock.call("command -v bwrap >/dev/null"),
    ]
