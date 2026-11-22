from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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


def _fallback_copy_probe():
    return """
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const [filename, root, home, requested] = process.argv.slice(1);
const sandbox = {
  __filename: filename,
  module: {exports:{}},
  console: {log(){}, error(){}},
  process: {platform:process.platform, env:{}, cwd:()=>home},
  require(name) {
    if (name === 'os') return {...require('os'), homedir:()=>home};
    if (name === 'child_process') return {spawnSync(){return {status:1};}};
    return require(name);
  },
};
vm.runInNewContext(fs.readFileSync(filename,'utf8') + '\\nglobalThis.probe={PROVIDERS,installProvider,skillDestBase};', sandbox, {filename});
const provider = sandbox.probe.PROVIDERS.find(item=>item.id === requested);
if (!provider || !sandbox.probe.installProvider(provider,root,{yes:true,dryRun:false})) throw new Error('Fallback failed');
console.log(JSON.stringify({base:sandbox.probe.skillDestBase(provider.profile),commands:path.join(home,'.cursor','commands','avo')}));
"""


@pytest.mark.parametrize(
    "profile", ["cursor", "claude", "codex", "windsurf", "cline", "gemini", "opencode"]
)
def test_fallback_installer_copies_organize_route_and_local_guidance(tmp_path, profile):
    import json

    home = tmp_path / "isolated-home"
    home.mkdir()
    result = subprocess.run(
        [
            "node",
            "-e",
            _fallback_copy_probe(),
            str(ROOT / "bin/install.cjs"),
            str(ROOT),
            str(home),
            profile,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout)
    pipeline = Path(paths["base"]) / "avo-pipeline"
    files = (
        "SKILL.md",
        "references/organize.md",
        "references/step-status.md",
        "references/command-map.md",
        "references/help.md",
        "references/arguments.md",
        "references/costs.md",
        "references/pipeline.md",
    )
    for relative in files:
        assert (pipeline / relative).read_bytes() == (
            ROOT / "agent-skills/avo-pipeline" / relative
        ).read_bytes()
    assert "/avo.organize" in (pipeline / "SKILL.md").read_text(encoding="utf-8")
    assert "`references/organize.md`" in (
        pipeline / "references/command-map.md"
    ).read_text(encoding="utf-8")
    assert "/avo.organize" in (pipeline / "references/help.md").read_text(
        encoding="utf-8"
    )
    if profile == "cursor":
        assert (Path(paths["commands"]) / "organize.md").read_bytes() == (
            ROOT / "commands/avo/organize.md"
        ).read_bytes()


def _install_engine_archive(home, archive, platform, asset):
    return subprocess.run(
        [
            "node",
            "-e",
            """
const fs = require('fs');
const vm = require('vm');
const [filename, home, archive, platform, asset, checksum] = process.argv.slice(1);
const base = 'https://github.com/joaobispo2077/avo/releases/download/v1.2.3/';
const requests = [];
const sandbox = {
  __filename: filename,
  module: {exports:{}},
  console: {log:message=>logs.push(message), error:console.error},
  process: {platform, arch:platform === 'darwin' ? 'arm64' : 'x64', env:{AVO_ENGINE_VERSION:'1.2.3'}},
  Buffer,
  require: name => name === 'os' ? {homedir:()=>home} : require(name),
  fetch: async url => {
    requests.push(url);
    if (url === base + 'SHA256SUMS') {
      return {ok:true, arrayBuffer:async()=>Buffer.from(`${checksum}  ${asset}\\n`)};
    }
    if (url === base + asset) return {ok:true, arrayBuffer:async()=>fs.readFileSync(archive)};
    throw new Error(`Unexpected request ${url}`);
  },
};
const logs = [];
vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\\nglobalThis.install=installEngine;', sandbox, {filename});
sandbox.install({}).then(
  () => console.log(JSON.stringify({requests, logs})),
  error => {console.error(error.message); process.exitCode = 1;},
);
""",
            str(ROOT / "bin/install.cjs"),
            str(home),
            str(archive),
            platform,
            asset,
            hashlib.sha256(archive.read_bytes()).hexdigest(),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize(
    ("platform", "slug", "launcher", "archive_root", "previous_install"),
    [
        ("win32", "windows-x64", "avo.exe", "avo", False),
        ("win32", "windows-x64", "avo.exe", "avo", True),
        ("linux", "linux-x64", "avo", "avo", False),
        ("darwin", "macos-arm64", "avo", "avo", False),
        ("win32", "windows-x64", "avo.exe", "bin", True),
    ],
)
def test_installer_places_engine_and_runtime_at_launcher_path(
    tmp_path, platform, slug, launcher, archive_root, previous_install
):
    import json

    prefix = tmp_path / ".avo"
    installed = prefix / "bin" / launcher
    if previous_install:
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"previous launcher")
        (installed.parent / "unrelated.txt").write_bytes(b"keep")
    asset = f"avo-1.2.3-{slug}.zip"
    archive = tmp_path / asset
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as fixture:
        fixture.writestr(f"{archive_root}/{launcher}", b"new launcher")
        fixture.writestr(f"{archive_root}/_internal/engine-data", b"runtime data")
        fixture.writestr(f"{archive_root}/providers/avo.provider.schema.json", b"{}")

    result = _install_engine_archive(tmp_path, archive, platform, asset)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert [url.rsplit("/", 1)[-1] for url in output["requests"]] == [
        "SHA256SUMS",
        asset,
    ]
    assert output["logs"][-1] == f"engine: {installed}"
    assert installed.read_bytes() == b"new launcher"
    assert (installed.parent / "_internal/engine-data").read_bytes() == b"runtime data"
    assert (installed.parent / "providers/avo.provider.schema.json").is_file()
    assert not (prefix / "avo").exists()
    if previous_install:
        assert (installed.parent / "unrelated.txt").read_bytes() == b"keep"


def test_installer_rejects_archive_without_launcher_before_replacing_files(tmp_path):
    bin_dir = tmp_path / ".avo" / "bin"
    installed_data = bin_dir / "_internal" / "engine-data"
    installed_data.parent.mkdir(parents=True)
    installed_data.write_bytes(b"previous runtime")
    launcher = bin_dir / "avo.exe"
    launcher.write_bytes(b"previous launcher")
    asset = "avo-1.2.3-windows-x64.zip"
    archive = tmp_path / asset
    with ZipFile(archive, "w") as fixture:
        fixture.writestr("bin/_internal/engine-data", b"incomplete runtime")

    result = _install_engine_archive(tmp_path, archive, "win32", asset)

    assert result.returncode != 0
    assert "missing launcher" in result.stderr
    assert launcher.read_bytes() == b"previous launcher"
    assert installed_data.read_bytes() == b"previous runtime"
