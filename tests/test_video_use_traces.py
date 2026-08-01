from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths where video-use / browser-use/video-use is allowed (engine credit or routing).
ALLOWLIST_GLOBS = [
    "README.md",
    "install.md",
    "docs/avo-workflow.md",
    "docs/avo-pipeline/**",
    "docs/ci.md",
    "docs/launch.md",
    "docs/repo-layout.md",
    "docs/engine-vs-orchestrator.md",
    "agent-skills/avo-pipeline/**",
    "avo.config.json",
    "avo.dependencies.json",
    "scripts/setup.sh",
    "scripts/setup.ps1",
    "scripts/validate-prerequisites.sh",
    "tests/test_validate_dependencies.py",
    "tests/test_avo_config.py",
    "tests/test_install_scripts.py",
    "tests/test_video_use_traces.py",
    "specs/**",
    ".env.example",
    "helpers/transcribe.py",
    "install.md",
]

STALE_PATTERNS = [
    re.compile(r"# Video Use Constitution", re.I),
    re.compile(r"video-use-hyperframes-tooling", re.I),
    re.compile(r">Video Use<", re.I),
    re.compile(r"custom video-use workflow", re.I),
    re.compile(r"video-use EDL", re.I),
    re.compile(r"`video-use` session outputs", re.I),
]


def _allowed(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    for pattern in ALLOWLIST_GLOBS:
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
        elif rel == pattern:
            return True
    return False


class VideoUseTraceTests(unittest.TestCase):
    def test_package_lock_matches_package_json_name(self) -> None:
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock.get("name"), pkg.get("name"))
        self.assertEqual(pkg.get("name"), "avo")

    def test_constitution_is_avo(self) -> None:
        text = (ROOT / ".specify/memory/constitution.md").read_text(encoding="utf-8")
        self.assertIn("# AVO Constitution", text)
        self.assertNotIn("# Video Use Constitution", text)

    def test_workflow_svg_not_labeled_video_use(self) -> None:
        svg = (ROOT / "static/avo-workflow.svg").read_text(encoding="utf-8")
        self.assertNotRegex(svg, r">Video Use<", msg="workflow SVG should not label product Video Use")
        self.assertIn("AVO engine", svg)

    def test_no_stale_product_traces_outside_allowlist(self) -> None:
        offenders: list[str] = []
        scan_roots = [
            ROOT / "helpers",
            ROOT / "docs",
            ROOT / "tests",
            ROOT / "static",
            ROOT / ".specify",
            ROOT / "scripts",
            ROOT / "commands",
            ROOT / "agent-skills",
        ]
        root_files = [
            ROOT / "AGENTS.md",
            ROOT / "README.md",
            ROOT / "SKILL.md",
            ROOT / "package-lock.json",
        ]
        paths: list[Path] = [p for p in root_files if p.is_file()]
        for base in scan_roots:
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    paths.append(path)
        for path in paths:
            if path.suffix not in {".md", ".json", ".py", ".svg", ".sh", ".ps1", ".cjs", ".yml", ".yaml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pat in STALE_PATTERNS:
                if pat.search(text) and not _allowed(path):
                    offenders.append(f"{rel}: {pat.pattern}")
        self.assertEqual(offenders, [], msg="Stale video-use product traces:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
