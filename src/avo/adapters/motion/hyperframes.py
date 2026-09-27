"""Constrained HyperFrames subprocess adapter for generated Shorts projects."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, ClassVar

from avo import shorts_contract
from avo.adapters.base import JobRequest, JobResult
from avo.paths import repo_root
from avo.shorts_media import SFX_ASSET_KEY, SFX_FILE_NAME, SFX_VOLUME

Runner = Callable[..., subprocess.CompletedProcess[str]]
TEMPLATE_VERSION = "shorts-anchor-rail-v4"
FORBIDDEN_COPY = ("COMPARATIVO SEM HYPE", "GAMEPLAY ILUSTRATIVA")
STAR_PATH = (
    "M12 2.4l2.86 5.8 6.4.93-4.63 4.51 1.09 6.36L12 16.97 6.28 20l1.09-6.36"
    "L2.74 9.13l6.4-.93L12 2.4z"
)


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
        if any(
            abs(float(region[key]) - expected) > 1e-9
            for key, expected in (("x", 0), ("y", 0), ("width", 1), ("height", 1))
        ):
            raise HyperframesError("full-frame base region must cover the canvas")
        return
    base = layout["baseRegion"]
    insertion = layout.get("insertionRegion")
    if not insertion or not _rect_inside(base) or not _rect_inside(insertion):
        raise HyperframesError("split layout requires two in-bounds regions")
    area = float(base["width"]) * float(base["height"]) + float(
        insertion["width"]
    ) * float(insertion["height"])
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


_LAYOUT_KEYS = {
    "mode",
    "captionAnchor",
    "baseRegion",
    "insertionRegion",
    "paneOrder",
    "focusPoint",
    "safeMargins",
}


def _normalized_layout(item: Mapping[str, Any]) -> dict[str, Any]:
    layout = dict(item["layout"])
    if "baseRegion" not in layout:
        if layout["mode"] == "full-frame":
            layout["baseRegion"] = {"x": 0, "y": 0, "width": 1, "height": 1}
        else:
            ratio = float(layout.get("splitRatio", 0.5))
            layout["baseRegion"] = {"x": 0, "y": 0, "width": 1, "height": ratio}
            layout["insertionRegion"] = {
                "x": 0,
                "y": ratio,
                "width": 1,
                "height": 1 - ratio,
            }
    layout = {key: value for key, value in layout.items() if key in _LAYOUT_KEYS}
    validate_geometry(layout)
    return layout


def _motion_fields(
    item: Mapping[str, Any], assets: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    motion = {
        "callouts": list(item.get("callouts") or []),
        "punchIns": list(item.get("punchIns") or []),
        "graphics": list(item.get("graphics") or []),
        "sfxHits": list(item.get("sfxHits") or []),
    }
    if any(motion.values()) or any(key.startswith("sfx") for key in assets):
        return motion
    return None


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
    layout = _normalized_layout(item)
    if layout["mode"] == "split" and not assets.get("insertionVideo"):
        raise HyperframesError("split layout requires prepared insertion video")
    motion = _motion_fields(item, assets)
    spec = {
        "version": "1.2" if motion else "1.0",
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
    if motion:
        spec.update(motion)
    shorts_contract.validate_document(spec, "composition")
    return spec


def _asset_source(spec: Mapping[str, Any], key: str) -> Path | None:
    value = spec["assets"].get(key)
    return Path(value["path"]).resolve() if value else None


def _ui_scale(spec: Mapping[str, Any]) -> float:
    """Overlay tokens are authored at 1080×1920; scale by canvas width / 1080."""
    width = float(spec.get("width") or 1080)
    return width / 1080.0 if width else 1.0


def _scaled_px(value: Any, scale: float, default: float) -> str:
    raw = str(value or "").strip().removesuffix("px")
    try:
        number = float(raw)
    except ValueError:
        number = default
    return f"{number * scale:.4g}px"


def _token_css(spec: Mapping[str, Any]) -> str:
    tokens = spec["providerTokens"]
    layout = spec["layout"]
    scale = _ui_scale(spec)
    margins = layout.get("safeMargins") or {}
    focus = layout.get("focusPoint") or {"x": 0.5, "y": 0.5}
    split = float(layout.get("baseRegion", {}).get("height", 0.5)) * 100
    return " ".join(
        (
            f"--ui-scale:{scale:.6g};",
            f"--short-ink:{tokens['ink']};",
            f"--short-rail:{tokens['rail']};",
            f"--short-accent:{tokens['accent']};",
            f"--short-punch:{tokens['punch']};",
            f"--short-font:{tokens['font']};",
            f"--short-rail-width:{_scaled_px(tokens.get('railWidth'), scale, 920)};",
            f"--short-safe-x:{_scaled_px(margins.get('left'), scale, 54)};",
            f"--short-safe-top:{_scaled_px(margins.get('top'), scale, 150)};",
            f"--short-safe-bottom:{_scaled_px(margins.get('bottom'), scale, 260)};",
            f"--focus-x:{float(focus['x']) * 100:.3f}%;",
            f"--focus-y:{float(focus['y']) * 100:.3f}%;",
            f"--split-percent:{split:.3f}%;",
        )
    )


def _caption_markup(phrases: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for phrase in phrases:
        words = []
        for word in phrase["words"]:
            classes = "caption-word" + (" is-punch" if word.get("punch") else "")
            words.append(
                f'<span id="{html.escape(str(word["id"]), quote=True)}" class="{classes}">'
                f"{word['text']}</span>"
            )
        rows.append(
            f'<div id="{html.escape(str(phrase["id"]), quote=True)}" '
            f'class="caption-phrase">{" ".join(words)}</div>'
        )
    return "\n".join(rows)


def _callout_markup(callouts: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for callout in callouts:
        kind = html.escape(str(callout.get("kind") or "chip"), quote=True)
        corner = html.escape(str(callout.get("corner") or "bl"), quote=True)
        cid = html.escape(str(callout["id"]), quote=True)
        text = html.escape(str(callout["text"]))
        rows.append(
            f'<div id="{cid}" class="callout callout-{kind} corner-{corner}">{text}</div>'
        )
    return "\n".join(rows)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _text(value: Any) -> str:
    return html.escape(str(value))


def _graphic_shell(
    graphic: Mapping[str, Any],
    inner: str,
    extra_class: str = "",
    extra_attrs: str = "",
) -> str:
    cid = _esc(graphic["id"])
    widget = _esc(graphic["widget"])
    corner = _esc(graphic.get("corner") or "bl")
    extra = f" {extra_class}" if extra_class else ""
    attrs = f" {extra_attrs}" if extra_attrs else ""
    return (
        f'<div id="{cid}" class="graphic graphic-{widget} corner-{corner}{extra}"{attrs}>'
        f"{inner}</div>"
    )


def _stars_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    total = max(1, int(params.get("total") or 5))
    label = params.get("label")
    stars = []
    for index in range(1, total + 1):
        sid = _esc(f"{graphic['id']}-star-{index}")
        stars.append(
            f'<span id="{sid}" class="graphic-star">'
            f'<svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path class="star-outline" d="{STAR_PATH}"></path>'
            f'<path class="star-fill" d="{STAR_PATH}"></path>'
            f"</svg></span>"
        )
    inner = f'<div class="graphic-stars-row">{"".join(stars)}</div>'
    if label:
        inner += f'<div class="graphic-label">{_text(label)}</div>'
    return _graphic_shell(graphic, inner)


def _stack_resolve_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    plates = []
    for index, item in enumerate(params.get("items") or [], 1):
        text = item.get("text") if isinstance(item, Mapping) else item
        pid = _esc(f"{graphic['id']}-plate-{index}")
        plates.append(f'<div id="{pid}" class="stack-plate">{_text(text)}</div>')
    lockup_id = _esc(f"{graphic['id']}-lockup")
    lockup = _text(params.get("resolve") or "")
    inner = (
        "".join(plates) + f'<div id="{lockup_id}" class="stack-lockup">{lockup}</div>'
    )
    return _graphic_shell(graphic, inner)


def _vs_reject_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    reject = params.get("reject") or {}
    confirm = params.get("confirm") or {}
    badge = params.get("badge") or {}
    rid = _esc(f"{graphic['id']}-reject")
    cid = _esc(f"{graphic['id']}-confirm")
    bid = _esc(f"{graphic['id']}-badge")
    inner = (
        f'<div id="{rid}" class="vs-tile vs-reject">'
        f"{_text(reject.get('text') or '')}"
        f'<span class="vs-x" aria-hidden="true">X</span></div>'
        f'<div id="{cid}" class="vs-tile vs-confirm">'
        f"{_text(confirm.get('text') or '')}</div>"
        f'<div id="{bid}" class="vs-badge">{_text(badge.get("text") or "")}</div>'
    )
    return _graphic_shell(graphic, inner)


def _flip_180_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    card = _esc(f"{graphic['id']}-card")
    inner = (
        f'<div id="{card}" class="flip-card" data-layout-allow-overlap="true">'
        f'<div class="flip-face flip-front">{_text(params.get("front") or "")}</div>'
        f'<div class="flip-face flip-back">'
        f"{_text(params.get('back') or '')}</div>"
        f"</div>"
    )
    return _graphic_shell(
        graphic, inner, extra_attrs='data-layout-allow-overlap="true"'
    )


def _cover_wipe_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    cover_id = _esc(f"{graphic['id']}-cover")
    inner = (
        f'<div class="wipe-stage" data-layout-allow-overflow="true" data-layout-allow-occlusion="true">'
        f'<div class="wipe-panel" data-layout-allow-occlusion="true">{_text(params.get("hidden") or "")}</div>'
        f'<div id="{cover_id}" class="wipe-cover" data-layout-allow-overflow="true" data-layout-allow-occlusion="true">'
        f"{_text(params.get('cover') or '')}</div>"
        f"</div>"
    )
    return _graphic_shell(
        graphic, inner, extra_attrs='data-layout-allow-overflow="true"'
    )


def _ratio_lock_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    inner = (
        f'<div class="ratio-frame"><span class="ratio-label">'
        f"{_text(params.get('ratio') or '')}</span></div>"
    )
    return _graphic_shell(graphic, inner)


def _duration_meter_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    fill_id = _esc(f"{graphic['id']}-fill")
    meta_id = _esc(f"{graphic['id']}-metacritic")
    hours = params.get("label") or params.get("hours") or ""
    inner = (
        f'<div class="meter-block">'
        f'<div class="meter-label">{_text(hours)}</div>'
        f'<div class="meter-track"><span id="{fill_id}" class="meter-fill"></span></div>'
        f"</div>"
        f'<div id="{meta_id}" class="meter-meta">{_text(params.get("metacritic") or "")}</div>'
    )
    return _graphic_shell(graphic, inner)


def _two_roles_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    roles = params.get("roles") or []
    tiles = []
    for index, role in enumerate(roles, 1):
        text = role.get("text") if isinstance(role, Mapping) else role
        rid = _esc(f"{graphic['id']}-role-{index}")
        tiles.append(f'<div id="{rid}" class="role-tile">{_text(text)}</div>')
    down_id = _esc(f"{graphic['id']}-downbeat")
    inner = (
        f'<div class="role-row">{"".join(tiles)}</div>'
        f'<div id="{down_id}" class="role-downbeat">'
        f"{_text(params.get('downbeat') or '')}</div>"
    )
    return _graphic_shell(graphic, inner)


def _badge_pair_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    badges = params.get("badges") or []
    chips = []
    for index, badge in enumerate(badges, 1):
        text = badge.get("text") if isinstance(badge, Mapping) else badge
        bid = _esc(f"{graphic['id']}-badge-{index}")
        chips.append(f'<div id="{bid}" class="pair-badge">{_text(text)}</div>')
    return _graphic_shell(graphic, f'<div class="badge-row">{"".join(chips)}</div>')


def _price_duel_markup(graphic: Mapping[str, Any]) -> str:
    params = graphic.get("params") or {}
    physical = _esc(f"{graphic['id']}-physical")
    digital = _esc(f"{graphic['id']}-digital")
    inner = (
        f'<div id="{physical}" class="price-tag price-physical">'
        f"{_text(params.get('physical') or '')}</div>"
        f'<div id="{digital}" class="price-tag price-digital">'
        f"{_text(params.get('digital') or '')}</div>"
    )
    return _graphic_shell(graphic, inner, extra_class="price-duel-row")


_WIDGET_MARKUP = {
    "stars": _stars_markup,
    "stack-resolve": _stack_resolve_markup,
    "vs-reject": _vs_reject_markup,
    "flip-180": _flip_180_markup,
    "cover-wipe": _cover_wipe_markup,
    "ratio-lock": _ratio_lock_markup,
    "duration-meter": _duration_meter_markup,
    "two-roles": _two_roles_markup,
    "badge-pair": _badge_pair_markup,
    "price-duel": _price_duel_markup,
}


def _graphic_markup(graphics: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for graphic in graphics:
        widget = str(graphic.get("widget") or "")
        builder = _WIDGET_MARKUP.get(widget)
        if builder is None:
            raise HyperframesError(f"unknown graphic widget: {widget}")
        rows.append(builder(graphic))
    return "\n".join(rows)


def _sfx_markup(spec: Mapping[str, Any]) -> str:
    duration = float(spec["durationSec"])
    rows = []
    for index, hit in enumerate(spec.get("sfxHits") or []):
        kind = str(hit["kind"])
        asset_key = SFX_ASSET_KEY[kind]
        asset = spec["assets"].get(asset_key)
        if not asset:
            raise HyperframesError(f"SFX hit {hit['id']} missing asset {asset_key}")
        start = float(hit["startSec"])
        play = min(float(asset["durationSec"]), duration - start)
        if play <= 1e-6:
            continue
        cid = html.escape(str(hit["id"]), quote=True)
        src = html.escape(SFX_FILE_NAME[asset_key], quote=True)
        rows.append(
            "      "
            f'<audio id="{cid}" src="assets/{src}" '
            f'data-start="{start:.6f}" data-duration="{play:.6f}" '
            f'data-track-index="{20 + index}" '
            f'data-volume="{SFX_VOLUME[kind]}"></audio>'
        )
    return "\n".join(rows)


def _script_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def _write_hyperframes_manifest(
    spec: Mapping[str, Any], template_root: Any, project_dir: Path
) -> None:
    manifest = json.loads(
        template_root.joinpath("hyperframes.json").read_text(encoding="utf-8")
    )
    manifest["fps"] = float(spec["fps"])
    manifest["renderContract"]["width"] = int(spec["width"])
    manifest["renderContract"]["height"] = int(spec["height"])
    (project_dir / "hyperframes.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def _copy_spec_assets(spec: Mapping[str, Any], assets_dir: Path) -> None:
    gsap = repo_root() / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if not gsap.is_file():
        raise HyperframesError("pinned local GSAP asset is missing; run npm install")
    shutil.copy2(gsap, assets_dir / "gsap.min.js")
    asset_names = {
        "baseVideo": "base-video.mp4",
        "dialogueAudio": "dialogue-audio.m4a",
        "insertionVideo": "insertion-video.mp4",
        "insertionAudio": "insertion-audio.m4a",
        **SFX_FILE_NAME,
    }
    for key, name in asset_names.items():
        source = _asset_source(spec, key)
        if source is None:
            continue
        if not source.is_file():
            raise HyperframesError(f"declared asset does not exist: {source}")
        shutil.copy2(source, assets_dir / name)


def _insertion_markup(spec: Mapping[str, Any], duration: str) -> tuple[str, str]:
    video = ""
    audio = ""
    if spec["assets"].get("insertionVideo"):
        video = (
            '      <video id="insertion-video" class="clip media-pane insertion-pane" '
            f'src="assets/insertion-video.mp4" data-start="0" data-duration="{duration}" '
            'data-track-index="1" muted playsinline></video>'
        )
    if spec["assets"].get("insertionAudio"):
        audio = (
            '      <audio id="insertion-audio" src="assets/insertion-audio.m4a" '
            f'data-start="0" data-duration="{duration}" data-track-index="11" '
            'data-volume="0.25"></audio>'
        )
    return video, audio


def compile_project(spec: Mapping[str, Any], project_dir: Path) -> Path:
    """Compile one immutable static project; generated HTML is disposable."""
    shorts_contract.validate_document(spec, "composition")
    validate_geometry(spec["layout"])
    template_root = resources.files("avo.templates.shorts_hyperframes")
    project_dir.mkdir(parents=True, exist_ok=False)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir()
    (project_dir / "styles.css").write_text(
        template_root.joinpath("styles.css").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_hyperframes_manifest(spec, template_root, project_dir)
    runtime = template_root.joinpath("runtime.js").read_text(encoding="utf-8")
    (project_dir / "runtime.js").write_text(
        runtime.replace("__CAPTION_JSON__", _script_json(spec["captions"]))
        .replace("__CALLOUT_JSON__", _script_json(spec.get("callouts") or []))
        .replace("__PUNCHIN_JSON__", _script_json(spec.get("punchIns") or []))
        .replace("__GRAPHIC_JSON__", _script_json(spec.get("graphics") or [])),
        encoding="utf-8",
    )
    _copy_spec_assets(spec, assets_dir)
    duration = f"{float(spec['durationSec']):.6f}"
    insertion_video, insertion_audio = _insertion_markup(spec, duration)

    page = template_root.joinpath("index.html").read_text(encoding="utf-8")
    replacements = {
        "__WIDTH__": str(spec["width"]),
        "__HEIGHT__": str(spec["height"]),
        "__SHORT_ID__": html.escape(str(spec["shortId"]), quote=True),
        "__DURATION__": duration,
        "__LAYOUT_MODE__": spec["layout"]["mode"],
        "__PANE_ORDER__": spec["layout"].get("paneOrder", "base-first"),
        "__CAPTION_ANCHOR__": spec["layout"]["captionAnchor"],
        "__TOKEN_CSS__": _token_css(spec),
        "__INSERTION_MEDIA__": insertion_video,
        "__INSERTION_AUDIO__": insertion_audio,
        "__SFX_AUDIO__": _sfx_markup(spec),
        "__CAPTION_MARKUP__": _caption_markup(spec["captions"]),
        "__CALLOUT_MARKUP__": _callout_markup(spec.get("callouts") or []),
        "__GRAPHIC_MARKUP__": _graphic_markup(spec.get("graphics") or []),
    }
    for marker, value in replacements.items():
        page = page.replace(marker, str(value))
    if re.search(r"__[A-Z][A-Z_]+__", page):
        raise HyperframesError("unresolved template marker in generated composition")
    if any(label in page.upper() for label in FORBIDDEN_COPY):
        raise HyperframesError(
            "generated composition contains forbidden undeclared copy"
        )
    (project_dir / "index.html").write_text(page, encoding="utf-8")
    shorts_contract.atomic_write_json(project_dir / "composition.json", spec)
    motion = {
        "duration": spec["durationSec"],
        "assertions": [
            {"kind": "staysInFrame", "selector": "#caption-rail"},
            {"kind": "staysInFrame", "selector": "#callout-layer"},
            {"kind": "staysInFrame", "selector": "#graphic-layer"},
        ],
    }
    shorts_contract.atomic_write_json(project_dir / "index.motion.json", motion)
    return project_dir


class HyperframesAdapter:
    routing_id = "hyperframes"
    operations: ClassVar[set[str]] = {"check", "snapshot", "preview", "render"}

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

    def execute(
        self, operation: str, project: Path, *extra: str, root: Path | None = None
    ) -> JobResult:
        if operation not in self.operations:
            return JobResult(
                exit_code=2, stderr=f"unsupported HyperFrames operation: {operation}"
            )
        root = (root or repo_root()).resolve()
        command = [*self._binary(root), operation, str(project.resolve()), *extra]
        if operation == "check" and "--strict" not in command:
            command.append("--strict")
        completed = self.runner(
            command, cwd=root, text=True, capture_output=True, check=False
        )
        artifacts: list[Path] = []
        for directory in (project / "snapshots", project / "renders"):
            if directory.is_dir():
                artifacts.extend(
                    path for path in directory.rglob("*") if path.is_file()
                )
        return JobResult(
            exit_code=completed.returncode,
            artifact_paths=artifacts,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run(self, request: JobRequest) -> JobResult:
        if len(request.argv) < 2:
            return JobResult(
                exit_code=2,
                stderr="usage: <check|snapshot|preview|render> PROJECT [args]",
            )
        return self.execute(
            request.argv[0], Path(request.argv[1]), *request.argv[2:], root=request.root
        )

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
                "animation instance missing resolved fields: "
                + ", ".join(sorted(missing))
            )
        if not component_contract.get("lifecycle"):
            raise HyperframesError("animation component requires a declared lifecycle")
        for path in list(Path(project).rglob("*.html")) + list(
            Path(project).rglob("*.js")
        ):
            source = path.read_text(encoding="utf-8", errors="replace")
            forbidden = (
                "Math.random(",
                "Date.now(",
                "performance.now(",
                "fetch(",
                "http://",
                "https://",
            )
            if any(token in source for token in forbidden):
                raise HyperframesError(
                    f"nondeterministic/network animation source: {path}"
                )
        checked = self.execute("check", project, "--strict", root=root)
        if checked.exit_code != 0:
            raise HyperframesError(
                checked.stderr or checked.stdout or "HyperFrames check failed"
            )
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
            raise HyperframesError(
                rendered.stderr or rendered.stdout or "HyperFrames render failed"
            )
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
