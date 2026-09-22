"""Closed-vocabulary labels for beat-edit stills. Not Watch QC."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from avo.beat_edit import TECHNIQUE_IDS
from avo.paths import repo_root

VISION_PROMPT = """Label this video-edit still. Reply with JSON only, no markdown:
{"techniques":[<ids>],"confidence":<0-1>}
Allowed ids: card_carousel, punch_zoom, whip_bump, kinetic_text, flip_3d, stylize.
Use only ids clearly visible. Use [] if none of the six appear.
Do not invent other ids. Do not score Watch QC or quality."""
VISION_UNREACHABLE = (
    "Understand vision endpoint unreachable. "
    "Do not skip to an empty technique map."
)
ENDPOINT_MISSING = (
    "Understand vision endpoint is unset. Pin models.understand "
    "source.endpoint baseUrl and servedName, or set WATCHSKILL_CUSTOM_BASE_URL "
    "with servedName. Do not skip to an empty technique map."
)


def prompt_hash() -> str:
    return hashlib.sha256(VISION_PROMPT.encode("utf-8")).hexdigest()


def parse_label_text(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if "```" in raw:
        chunk = raw.split("```", 2)[1]
        raw = chunk.removeprefix("json")
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Vision model did not return JSON: {exc}") from exc
    techniques = [tid for tid in data.get("techniques") or [] if tid in TECHNIQUE_IDS]
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "techniques": techniques,
        "confidence": max(0.0, min(1.0, confidence)),
    }


def require_bonsai(root: Path | None = None) -> dict[str, str]:
    from avo.model_sources import PreflightError, preflight, resolve_job

    resolved = resolve_job("understand", root=root or repo_root(), label="local")
    try:
        preflight(resolved)
    except PreflightError as exc:
        raise RuntimeError(f"{exc.code}: {exc}") from exc
    source = (
        resolved.pin.get("source")
        if isinstance(resolved.pin.get("source"), dict)
        else {}
    )
    endpoint = (
        source.get("endpoint") if isinstance(source.get("endpoint"), dict) else {}
    )
    url = str(
        endpoint.get("baseUrl") or os.environ.get("WATCHSKILL_CUSTOM_BASE_URL") or ""
    ).rstrip("/")
    model = str(endpoint.get("servedName") or "")
    if not url or not model:
        raise RuntimeError(ENDPOINT_MISSING)
    return {"url": url, "model": model, "id": resolved.id}


def _post_chat(
    url: str, payload: dict[str, Any], *, timeout: int = 60
) -> dict[str, Any]:
    request = Request(
        f"{url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Understand vision HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(VISION_UNREACHABLE) from exc


def label_image(
    image_path: Path,
    *,
    url: str,
    model: str,
    post: Any = None,
) -> dict[str, Any]:
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ],
            }
        ],
    }
    sender = post or _post_chat
    body = sender(url, payload)
    content = ((body.get("choices") or [{}])[0].get("message") or {}).get(
        "content"
    ) or ""
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return parse_label_text(str(content))


def _t_from_name(path: Path) -> float:
    stem = path.stem
    if stem.startswith("t-"):
        try:
            return int(stem[2:]) / 1000.0
        except ValueError:
            return 0.0
    return 0.0


def label_frames_dir(
    frames_dir: Path,
    *,
    root: Path | None = None,
    post: Any = None,
    pin: dict[str, str] | None = None,
) -> dict[str, Any]:
    directory = Path(frames_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"technique frames folder not found: {directory}")
    images = sorted(
        p
        for p in directory.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not images:
        raise RuntimeError(f"no stills in {directory}")
    if pin is None:
        pin = require_bonsai(root)
    frames: list[dict[str, Any]] = []
    for image in images:
        t = _t_from_name(image)
        labeled = label_image(image, url=pin["url"], model=pin["model"], post=post)
        frames.append(
            {
                "t": t,
                "anchor": f"t:{t:.3f}",
                "path": str(image),
                **labeled,
            }
        )
    return {
        "model": pin.get("id") or pin["model"],
        "promptHash": prompt_hash(),
        "frames": frames,
    }
