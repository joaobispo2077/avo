from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_install_js_help_exits_zero(self) -> None:
        r = subprocess.run(
            ["node", "bin/install.cjs", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("AVO installer", r.stdout)

    def test_install_js_list_agents(self) -> None:
        r = subprocess.run(
            ["node", "bin/install.cjs", "--list"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("cursor", r.stdout)

    def test_install_js_dry_run_exits_zero(self) -> None:
        r = subprocess.run(
            ["node", "bin/install.cjs", "--dry-run", "--only", "cursor"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("dry-run", r.stdout.lower())

    def test_skills_json_exists(self) -> None:
        path = ROOT / "skills.json"
        self.assertTrue(path.is_file())

    def test_agent_skills_avo_exists(self) -> None:
        skill = ROOT / "agent-skills" / "avo" / "SKILL.md"
        self.assertTrue(skill.is_file())

    def test_skills_json_lists_all_avo_skills(self) -> None:
        import json

        data = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))
        names = {s["name"] for s in data.get("skills", [])}
        self.assertEqual(names, {"avo", "avo-pipeline", "avo-provider"})
        for entry in data["skills"]:
            self.assertTrue((ROOT / entry["path"]).is_file(), msg=entry["path"])

    def test_default_repo_slug(self) -> None:
        src = (ROOT / "bin" / "install.cjs").read_text(encoding="utf-8")
        self.assertIn("joaobispo2077/avo", src)
        self.assertNotIn("'browser-use/video-use'", src)

    def test_install_sh_default_repo(self) -> None:
        sh = (ROOT / "scripts" / "install" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("joaobispo2077/avo", sh)

    def test_install_scripts_resolve_repo_root(self) -> None:
        sh = (ROOT / "scripts" / "install" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("script_dir/../..", sh)

    def test_skills_json_repo_slug(self) -> None:
        import json

        data = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))
        self.assertEqual(data.get("repository"), "joaobispo2077/avo")


if __name__ == "__main__":
    unittest.main()


# Canonical CLI IDs differ from AVO's stable --only/fallback profile IDs.
# Capturing argv is a contract check, not proof that the real CLI copied a tree.
def test_normal_installer_preserves_user_profile_ids():
    import json

    result = subprocess.run(
        [
            "node",
            "-e",
            _skills_invocation_probe(),
            str(ROOT / "bin/install.cjs"),
            "cursor",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ids"] == [
        "cursor",
        "claude",
        "codex",
        "windsurf",
        "cline",
        "gemini",
        "opencode",
    ]


def _skills_invocation_probe():
    return """
const fs = require('fs');
const vm = require('vm');
const filename = process.argv[1];
const requested = process.argv[2];
const calls = [];
const sandbox = {
  __filename: filename,
  module: {exports:{}},
  console: {log(){}, error(){}},
  process: {platform:process.platform, env:{AVO_INSTALL_REPO:'example/avo',AVO_INSTALL_REF:'test-ref'}},
  require(name) {
    if (name === 'child_process') return {spawnSync(command, args) {calls.push({command,args}); return {status:0};}};
    return require(name);
  },
};
vm.runInNewContext(fs.readFileSync(filename,'utf8') + '\\nglobalThis.probe={PROVIDERS,installProvider};', sandbox, {filename});
const provider = sandbox.probe.PROVIDERS.find(item => item.id === requested);
if (!provider) throw new Error('Unknown profile ' + requested);
if (!sandbox.probe.installProvider(provider, null, {yes:true,dryRun:false})) throw new Error('Installer failed');
console.log(JSON.stringify({ids:sandbox.probe.PROVIDERS.map(item=>item.id),calls}));
"""


@pytest.mark.parametrize(
    "profile,canonical",
    [
        ("cursor", "cursor"),
        ("claude", "claude-code"),
        ("codex", "codex"),
        ("windsurf", "windsurf"),
        ("cline", "cline"),
        ("gemini", "gemini-cli"),
        ("opencode", "opencode"),
    ],
)
def test_normal_installer_uses_supported_canonical_skills_agent_ids(profile, canonical):
    import json

    result = subprocess.run(
        [
            "node",
            "-e",
            _skills_invocation_probe(),
            str(ROOT / "bin/install.cjs"),
            profile,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)["calls"]
    assert len(calls) == 1
    assert calls[0]["command"] == "npx"
    arguments = calls[0]["args"]
    assert arguments[:4] == ["-y", "skills", "add", "github:example/avo#test-ref"]
    assert arguments[arguments.index("-a") + 1] == canonical
    assert "--yes" in arguments
