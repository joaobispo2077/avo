"""Render complete offline visual/text snapshots from immutable proposals."""

from __future__ import annotations

import base64
import hashlib
import json
from importlib import resources

from avo.library.rules import safe_path
from avo.timeline.store import now_iso


def render_review(root, proposal, context):
    assets = resources.files("avo.templates.library_review")
    script = assets.joinpath("review.js").read_text(encoding="utf-8")
    style = assets.joinpath("review.css").read_text(encoding="utf-8")
    template = assets.joinpath("index.html").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    csp = f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'"
    context = {**context, "generatedAt": now_iso()}
    payload = json.dumps({"context": context, "proposal": proposal}, ensure_ascii=True)
    payload = (
        payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    rendered = (
        template.replace("__CSP__", csp)
        .replace("__STYLE__", style)
        .replace("__DATA__", payload)
        .replace("__SCRIPT__", script)
    )
    name = f"{proposal['proposalId']}-{proposal['revision']}"
    html_path = safe_path(root, f"edit/library/review/{name}.html")
    text_path = safe_path(root, f"edit/library/review/{name}.md")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(rendered, encoding="utf-8")
    lines = [
        "# Library organization review",
        "",
        f"Snapshot: {context['generatedAt']}",
        f"Provider: {context['provider']}",
        f"Root: {root}",
        "",
        "No files move until native preparation and explicit approval.",
        "",
    ]
    for group in proposal["groups"]:
        lines.extend([f"## {group['label']}", group["rationale"], ""])
        for action in proposal["actions"]:
            if action["groupId"] == group["id"]:
                lines.append(
                    f"{action['recordingId']} | {action['status']} | {action['from']} -> {action['to']} | {action['reason']}"
                )
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"html": html_path, "text": text_path}
