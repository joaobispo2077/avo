"""Portable code-drawn delivery through real fallback and skills CLI paths.

The normal-path argv unit test lives in test_install_scripts.py. Only the optional
real CLI matrix below proves normal installation; a copied test tree is not proof.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from hashlib import sha256
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = ROOT / "agent-skills/avo-pipeline"
SKILL_NAMES = {"avo", "avo-pipeline", "avo-provider"}
GUIDES = (
    "references/code-drawn.md",
    "references/code-drawn/selection.md",
    "references/code-drawn/setup.md",
    "references/code-drawn/render-contract.md",
    "references/code-drawn/creative.md",
    "references/code-drawn/motion-techniques.md",
    "references/code-drawn/audio.md",
    "references/code-drawn/qc-delivery.md",
    "references/code-drawn/troubleshooting.md",
    "references/code-drawn/sources.md",
)
PROFILES = (
    ("cursor", "cursor", ".cursor/skills", ".agents/skills"),
    ("claude", "claude-code", ".claude/skills", ".claude/skills"),
    ("codex", "codex", ".codex/skills", ".agents/skills"),
    ("windsurf", "windsurf", ".codeium/windsurf/skills", ".windsurf/skills"),
    ("cline", "cline", ".cline/skills", ".agents/skills"),
    ("gemini", "gemini-cli", ".gemini/skills", ".agents/skills"),
    ("opencode", "opencode", ".config/opencode/skills", ".agents/skills"),
)
SKILLS_CLI_VERSION = "1.7.4"


def isolated_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
    }


def assert_portable_guide_links(skill: Path) -> None:
    root = skill.resolve()
    for relative in GUIDES:
        guide = skill / relative
        assert guide.is_file(), f"Missing installed guide: {relative}"
        text = guide.read_text(encoding="utf-8")
        for raw in re.findall(r"!?\[[^\]]*\]\(([^)\n]+)\)", text):
            target = raw.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme in {"https", "http"}:
                continue
            assert not parsed.scheme and not parsed.netloc, (relative, target)
            if not parsed.path:
                continue
            path = Path(unquote(parsed.path))
            assert not path.is_absolute(), (relative, target)
            assert not {".agents", ".claude", ".codex"} & set(path.parts), (
                relative,
                target,
            )
            resolved = (guide.parent / path).resolve()
            assert resolved.is_relative_to(root), (
                f"{relative} escapes installed skill: {target}"
            )
            assert resolved.is_file(), (
                f"{relative} has missing installed reference: {target}"
            )


def assert_installed_bundle(base: Path) -> None:
    names = {entry.name for entry in base.iterdir() if (entry / "SKILL.md").is_file()}
    assert names == SKILL_NAMES
    pipeline = base / "avo-pipeline"
    for relative in GUIDES:
        installed = pipeline / relative
        source = SOURCE_SKILL / relative
        assert installed.is_file(), f"Missing installed guide: {relative}"
        assert not installed.is_symlink(), (
            f"Expected copied guide, not source link: {relative}"
        )
        assert (
            sha256(installed.read_bytes()).digest()
            == sha256(source.read_bytes()).digest()
        )
    assert_portable_guide_links(pipeline)


def test_exact_ten_guides_have_single_portable_owner() -> None:
    actual = {
        str(path.relative_to(SOURCE_SKILL)).replace("\\", "/")
        for path in [
            SOURCE_SKILL / "references/code-drawn.md",
            *(SOURCE_SKILL / "references/code-drawn").glob("*.md"),
        ]
        if path.is_file()
    }
    assert actual == set(GUIDES), f"Missing guides: {set(GUIDES) - actual}"
    manifest = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))
    assert {entry["name"] for entry in manifest["skills"]} == SKILL_NAMES
    assert_portable_guide_links(SOURCE_SKILL)


@pytest.mark.parametrize(
    "profile,_canonical,fallback,_project", PROFILES, ids=[p[0] for p in PROFILES]
)
def test_actual_fallback_recursively_copies_complete_bundle(
    tmp_path, profile, _canonical, fallback, _project
):
    home = tmp_path / "home"
    script = """
const os = require('os');
os.homedir = () => process.argv[3];
const installer = require(process.argv[1]);
if (!installer.installSkillsFallback(process.argv[2], process.argv[4], {dryRun:false})) {
  throw new Error('Fallback did not install skills');
}
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "bin/install.cjs"),
            str(ROOT),
            str(home),
            profile,
        ],
        cwd=tmp_path,
        env=isolated_environment(home),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert_installed_bundle(home / fallback)


@pytest.fixture(scope="module")
def real_skills_cli(tmp_path_factory):
    declared = os.environ.get("AVO_SKILLS_CLI")
    if not declared:
        if os.environ.get("AVO_REQUIRE_SKILLS_CLI") == "1":
            pytest.fail("Required real skills CLI matrix needs AVO_SKILLS_CLI.")
        pytest.skip(
            "Real normal-install proof requires pinned AVO_SKILLS_CLI; argv unit tests are separate."
        )
    cli = Path(declared).resolve()
    assert cli.is_file(), cli
    version_home = tmp_path_factory.mktemp("skills-cli-version-home")
    version = subprocess.run(
        ["node", str(cli), "--version"],
        cwd=version_home,
        env=isolated_environment(version_home),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == SKILLS_CLI_VERSION
    return cli


@pytest.mark.integration
@pytest.mark.parametrize(
    "_profile,canonical,_fallback,project", PROFILES, ids=[p[0] for p in PROFILES]
)
def test_real_skills_cli_installs_local_bundle_for_each_canonical_agent(
    tmp_path, real_skills_cli, _profile, canonical, _fallback, project
):
    """Exercise the real published CLI, never a fake copy implementation."""
    home = tmp_path / "home"
    workspace = tmp_path / "external-project"
    workspace.mkdir()
    result = subprocess.run(
        [
            "node",
            str(real_skills_cli),
            "add",
            str(ROOT / "agent-skills"),
            "--copy",
            "--yes",
            "-a",
            canonical,
            "--skill",
            "avo",
            "avo-pipeline",
            "avo-provider",
        ],
        cwd=workspace,
        env=isolated_environment(home),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert_installed_bundle(workspace / project)
    assert not any((home / path).exists() for _id, _agent, path, _project in PROFILES)


@pytest.mark.parametrize("route", ["canvas", "svg", "brush"])
def test_native_package_resources_have_one_executable_starter_owner(route):
    package = resources.files("avo.templates.code_drawn")
    assert package.joinpath(route, "index.html").is_file()
    assert "window.seek" in "".join(
        path.read_text(encoding="utf-8")
        for path in package.joinpath(route).iterdir()
        if path.is_file() and path.name.endswith((".html", ".js"))
    )
    assert not (SOURCE_SKILL / "references/code-drawn" / route / "index.html").exists()


@pytest.mark.parametrize(
    "document",
    [
        "DESIGN.md",
        "STORYBOARD.md",
        "ANIMATION-EDITLOG.md",
        "ANIMATION-SOURCE-LOG.md",
        "README.md",
        "SCRIPT.md",
        "REVIEW.md",
        "DELIVERY.md",
    ],
)
def test_native_package_resources_include_complete_project_documents(document):
    package = resources.files("avo.templates.code_drawn")
    assert package.joinpath("project-documents", document).is_file(), document
