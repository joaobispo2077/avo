"""Constrained HyperFrames subprocess adapter for generated Shorts projects."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from avo import shorts_contract
from avo.adapters.base import JobRequest, JobResult
from avo.paths import repo_root

Runner = Callable[..., subprocess.CompletedProcess[str]]
TEMPLATE_VERSION = "shorts-anchor-rail-v1"
FORBIDDEN_COPY = ("COMPARATIVO SEM HYPE", "GAMEPLAY ILUSTRATIVA")


class HyperframesError(RuntimeError):
    """A composition or HyperFrames operation violated its contract."""


def _rect_inside(rect: Mapping[str, Any]) -> bool:
    return (
        0 <= float(rect["x"]) <= 1
        and 0 <= float(rect["y"]) <= 1
        and float(rect["width"]) > 0
        and float(rect["height"]) > 0
        and float(rect["x"]) + float(rect["width"]) <= 1 + 1e-9
        and float(rect["y"]) + float(rect["height"]) <= 1 + 1e-9
    )


def validate_geometry(layout: Mapping[str, Any]) -> None:
    mode = layout["mode"]
    anchor = layout["captionAnchor"]
    if mode == "full-frame":
        if anchor == "seam":
            raise HyperframesError("seam anchor requires split layout")
        region = layout["baseRegion"]
        if any(abs(float(region[key]) - expected) > 1e-9 for key, expected in (
            ("x", 0), ("y", 0), ("width", 1), ("height", 1)
        )):
            raise HyperframesError("full-frame base region must cover the canvas")
        return
    base = layout["baseRegion"]
    insertion = layout.get("insertionRegion")
    if not insertion or not _rect_inside(base) or not _rect_inside(insertion):
        raise HyperframesError("split layout requires two in-bounds regions")
    area = float(base["width"]) * float(base["height"]) + float(insertion["width"]) * float(insertion["height"])
    if abs(area - 1) > 1e-6:
        raise HyperframesError("split regions must fill the canvas exactly")


def resolve_provider_tokens(tokens: Mapping[str, Any] | None) -> dict[str, str]:
    defaults = {
        "ink": "#fff8f0",
        "rail": "rgba(14, 12, 18, 0.88)",
        "accent": "#ffd21f",
        "punch": "#ff5b45",
        "font": "sans-serif",
        "railWidth": "920px",
    }
    for key, value in (tokens or {}).items():
        if key in defaults and isinstance(value, (str, int, float)):
            defaults[key] = str(value)
    return defaults


def build_composition_spec(
    *,
    batch_id: str,
    item: Mapping[str, Any],
    output: Mapping[str, Any],
    assets: Mapping[str, Mapping[str, Any]],
    proof_revision: int,
    expected_output_path: Path,
    provider_tokens: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    layout = dict(item["layout"])
    if "baseRegion" not in layout:
        if layout["mode"] == "full-frame":
            layout["baseRegion"] = {"x": 0, "y": 0, "width": 1, "height": 1}
        else:
            ratio = float(layout.get("splitRatio", .5))
            layout["baseRegion"] = {"x": 0, "y": 0, "width": 1, "height": ratio}
            layout["insertionRegion"] = {"x": 0, "y": ratio, "width": 1, "height": 1 - ratio}
    allowed_layout = {
        "mode", "captionAnchor", "baseRegion", "insertionRegion",
        "paneOrder", "focusPoint", "safeMargins",
    }
    layout = {key: value for key, value in layout.items() if key in allowed_layout}
    validate_geometry(layout)
    if layout["mode"] == "split" and not assets.get("insertionVideo"):
        raise HyperframesError("split layout requires prepared insertion video")
    spec = {
        "version": "1.0",
        "batchId": batch_id,
        "shortId": str(item["id"]),
        "proofRevision": proof_revision,
        "width": int(output["width"]),
        "height": int(output["height"]),
        "fps": float(output["fps"]),
        "durationSec": float(item["editedDurationSec"]),
        "assets": dict(assets),
        "layout": layout,
        "captions": list(item.get("captions") or []),
        "providerTokens": resolve_provider_tokens(provider_tokens),
        "templateVersion": TEMPLATE_VERSION,
        "expectedTimelineCount": 1,
        "expectedOutputPath": str(expected_output_path),
        "provenanceReferences": list(item.get("factualReviewReferences") or []),
    }
    shorts_contract.validate_document(spec, "composition")
    return spec


def _asset_source(spec: Mapping[str, Any], key: str) -> Path | None:
    value = spec["assets"].get(key)
    return Path(value["path"]).resolve() if value else None


def _token_css(spec: Mapping[str, Any]) -> str:
    tokens = spec["providerTokens"]
    layout = spec["layout"]
    focus = layout.get("focusPoint") or {"x": .5, "y": .5}
    split = float(layout.get("baseRegion", {}).get("height", .5)) * 100
    return " ".join((
        f"--short-ink:{tokens['ink']};",
        f"--short-rail:{tokens['rail']};",
        f"--short-accent:{tokens['accent']};",
        f"--short-punch:{tokens['punch']};",
        f"--short-font:{tokens['font']};",
        f"--short-rail-width:{tokens['railWidth']};",
        f"--focus-x:{float(focus['x']) * 100:.3f}%;",
        f"--focus-y:{float(focus['y']) * 100:.3f}%;",
        f"--split-percent:{split:.3f}%;",
    ))


def _caption_markup(phrases: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for phrase in phrases:
        words = []
        for word in phrase["words"]:
            classes = "caption-word" + (" is-punch" if word.get("punch") else "")
            words.append(
                f'<span id="{html.escape(str(word["id"]), quote=True)}" class="{classes}">'
                f'{word["text"]}</span>'
            )
        rows.append(
            f'<div id="{html.escape(str(phrase["id"]), quote=True)}" '
            f'class="caption-phrase">{" ".join(words)}</div>'
        )
    return "\n".join(rows)


def compile_project(spec: Mapping[str, Any], project_dir: Path) -> Path:
    """Compile one immutable static project; generated HTML is disposable."""
    shorts_contract.validate_document(spec, "composition")
    validate_geometry(spec["layout"])
    serialized = json.dumps(spec["captions"], ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    template_root = resources.files("avo.templates.shorts_hyperframes")
    project_dir.mkdir(parents=True, exist_ok=False)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir()
    for name in ("styles.css", "hyperframes.json"):
        (project_dir / name).write_text(template_root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    runtime = template_root.joinpath("runtime.js").read_text(encoding="utf-8")
    (project_dir / "runtime.js").write_text(
        runtime.replace("__CAPTION_JSON__", serialized), encoding="utf-8"
    )

    gsap = repo_root() / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if not gsap.is_file():
        raise HyperframesError("pinned local GSAP asset is missing; run npm install")
    shutil.copy2(gsap, assets_dir / "gsap.min.js")
    asset_names = {
        "baseVideo": "base-video.mp4", "dialogueAudio": "dialogue-audio.m4a",
        "insertionVideo": "insertion-video.mp4", "insertionAudio": "insertion-audio.m4a",
    }
    for key, name in asset_names.items():
        source = _asset_source(spec, key)
        if source is not None:
            if not source.is_file():
                raise HyperframesError(f"declared asset does not exist: {source}")
            shutil.copy2(source, assets_dir / name)

    duration = f"{float(spec['durationSec']):.6f}"
    insertion_video = ""
    insertion_audio = ""
    if spec["assets"].get("insertionVideo"):
        insertion_video = f'''      <video id="insertion-video" class="clip media-pane insertion-pane" src="assets/insertion-video.mp4" data-start="0" data-duration="{duration}" data-track-index="1" muted playsinline></video>'''
    if spec["assets"].get("insertionAudio"):
        insertion_audio = f'''      <audio id="insertion-audio" src="assets/insertion-audio.m4a" data-start="0" data-duration="{duration}" data-track-index="11" data-volume="0.25"></audio>'''

    page = template_root.joinpath("index.html").read_text(encoding="utf-8")
    replacements = {
        "__WIDTH__": str(spec["width"]), "__HEIGHT__": str(spec["height"]),
        "__SHORT_ID__": html.escape(str(spec["shortId"]), quote=True),
        "__DURATION__": duration, "__LAYOUT_MODE__": spec["layout"]["mode"],
        "__PANE_ORDER__": spec["layout"].get("paneOrder", "base-first"),
        "__CAPTION_ANCHOR__": spec["layout"]["captionAnchor"],
        "__TOKEN_CSS__": _token_css(spec), "__INSERTION_MEDIA__": insertion_video,
        "__INSERTION_AUDIO__": insertion_audio,
        "__CAPTION_MARKUP__": _caption_markup(spec["captions"]),
    }
    for marker, value in replacements.items():
        page = page.replace(marker, str(value))
    if re.search(r"__[A-Z][A-Z_]+__", page):
        raise HyperframesError("unresolved template marker in generated composition")
    if any(label in page.upper() for label in FORBIDDEN_COPY):
        raise HyperframesError("generated composition contains forbidden undeclared copy")
    (project_dir / "index.html").write_text(page, encoding="utf-8")
    shorts_contract.atomic_write_json(project_dir / "composition.json", spec)
    motion = {
        "duration": spec["durationSec"],
        "assertions": [{"kind": "staysInFrame", "selector": "#caption-rail"}],
    }
    shorts_contract.atomic_write_json(project_dir / "index.motion.json", motion)
    return project_dir


class HyperframesAdapter:
    routing_id = "hyperframes"
    operations = {"check", "snapshot", "preview", "render"}

    def __init__(self, runner: Runner = subprocess.run) -> None:
        self.runner = runner

    def _binary(self, root: Path) -> list[str]:
        local = root / "node_modules" / ".bin" / "hyperframes"
        for candidate in (local.with_suffix(".cmd"), local.with_suffix(".ps1"), local):
            try:
                if candidate.is_file():
                    return [str(candidate)]
            except OSError:
                continue
        return ["npx", "--no-install", "hyperframes"]

    def execute(self, operation: str, project: Path, *extra: str, root: Path | None = None) -> JobResult:
        if operation not in self.operations:
            return JobResult(exit_code=2, stderr=f"unsupported HyperFrames operation: {operation}")
        root = (root or repo_root()).resolve()
        command = [*self._binary(root), operation, str(project.resolve()), *extra]
        if operation == "check" and "--strict" not in command:
            command.append("--strict")
        completed = self.runner(command, cwd=root, text=True, capture_output=True, check=False)
        artifacts: list[Path] = []
        for directory in (project / "snapshots", project / "renders"):
            if directory.is_dir():
                artifacts.extend(path for path in directory.rglob("*") if path.is_file())
        return JobResult(
            exit_code=completed.returncode,
            artifact_paths=artifacts,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run(self, request: JobRequest) -> JobResult:
        if len(request.argv) < 2:
            return JobResult(exit_code=2, stderr="usage: <check|snapshot|preview|render> PROJECT [args]")
        return self.execute(request.argv[0], Path(request.argv[1]), *request.argv[2:], root=request.root)


    def render_timeline_instance(
        self,
        *,
        project: Path,
        output: Path,
        instance: Mapping[str, Any],
        component_contract: Mapping[str, Any],
        root: Path | None = None,
        quality: str = "draft",
    ) -> dict[str, Any]:
        """Check then render one frozen, BMap-timed/Tracks-placed instance."""
        from avo.timeline.contracts import file_fingerprint

        required = {"componentRef", "bmapCueId", "placement", "range", "reducedMotion"}
        missing = required - set(instance)
        if missing:
            raise HyperframesError(
                "animation instance missing resolved fields: " + ", ".join(sorted(missing))
            )
        if not component_contract.get("lifecycle"):
            raise HyperframesError("animation component requires a declared lifecycle")
        for path in list(Path(project).rglob("*.html")) + list(Path(project).rglob("*.js")):
            source = path.read_text(encoding="utf-8", errors="replace")
            forbidden = ("Math.random(", "Date.now(", "performance.now(", "fetch(", "http://", "https://")
            if any(token in source for token in forbidden):
                raise HyperframesError(f"nondeterministic/network animation source: {path}")
        checked = self.execute("check", project, "--strict", root=root)
        if checked.exit_code != 0:
            raise HyperframesError(checked.stderr or checked.stdout or "HyperFrames check failed")
        rendered = self.execute(
            "render",
            project,
            "--quality",
            quality,
            "--output",
            str(output),
            root=root,
        )
        if rendered.exit_code != 0:
            raise HyperframesError(rendered.stderr or rendered.stdout or "HyperFrames render failed")
        if not Path(output).is_file():
            raise HyperframesError(f"HyperFrames output missing: {output}")
        return {
            "status": "pass",
            "output": file_fingerprint(Path(output)),
            "componentRef": instance["componentRef"],
            "bmapCueId": instance["bmapCueId"],
            "placement": dict(instance["placement"]),
            "range": dict(instance["range"]),
            "reducedMotion": bool(instance["reducedMotion"]),
            "producer": {"name": "hyperframes", "version": "installed"},
        }
