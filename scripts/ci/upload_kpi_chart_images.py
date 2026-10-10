#!/usr/bin/env python3
"""Host Software quality chart PNGs and rewrite sticky image links.

Prefers GitHub user-attachments when ``KPI_CHART_UPLOAD_TOKEN`` is a user token
(the Actions ``GITHUB_TOKEN`` cannot mint those URLs). Otherwise publishes the
PNGs on the ``ci/quality-kpi-charts`` branch and embeds raw.githubusercontent.com
URLs. A failed upload becomes an explicit note. Empty ``![]()`` is not written.

This step is visualization hosting. It exits 0 so it cannot flip a green
Software quality job red, and it does not change any gate floor.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IMAGE_PREFIX = "kpi-chart:"
HOST_BRANCH = "ci/quality-kpi-charts"
HOST_DIR = "quality-kpi-charts"
API = "https://api.github.com"
_IMAGE = re.compile(r"!\[([^\]]*)\]\(kpi-chart:([A-Za-z0-9._-]+)\)")
_TOKEN = re.compile(r"\b(gh[opsu]_|github_pat_)\w+")


class UploadError(RuntimeError):
    pass


def public_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    text = _TOKEN.sub("[token]", text)
    return text[:240]


def guarded_branch(branch: str) -> str:
    if branch != HOST_BRANCH:
        raise ValueError(f"refusing to publish charts to {branch}")
    return branch


def raw_githubusercontent_url(repo: str, branch: str, path: str) -> str:
    guarded_branch(branch)
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe chart path: {path}")
    if not repo or "/" not in repo or ".." in repo:
        raise ValueError(f"unsafe repository: {repo}")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def chart_object_path(run_id: str, filename: str) -> str:
    if not re.fullmatch(r"[0-9]{1,20}", run_id):
        raise ValueError(f"unsafe run id: {run_id}")
    if not re.fullmatch(r"[a-z0-9.-]+\.png", filename):
        raise ValueError(f"unsafe chart name: {filename}")
    return f"{HOST_DIR}/{run_id}/{filename}"


def apply_image_urls(
    markdown: str,
    urls: dict[str, str],
    errors: dict[str, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        alt, name = match.group(1), match.group(2)
        url = urls.get(name, "")
        if url.startswith("https://"):
            label = alt or name
            return f"![{label}]({url})"
        reason = errors.get(name) or "upload did not return a URL"
        label = alt or name
        return f"**Chart image unavailable ({label}):** {public_error(RuntimeError(reason))}."

    updated = _IMAGE.sub(replace, markdown)
    if "kpi-chart:" in updated or "![](" in updated:
        raise UploadError("refusing to leave an empty or unresolved chart image")
    return updated


def strip_unresolved(markdown: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(1) or match.group(2)
        return f"**Chart image unavailable ({label}):** unresolved image reference."

    return _IMAGE.sub(replace, markdown)


def referenced_charts(markdown: str) -> list[str]:
    return [match.group(2) for match in _IMAGE.finditer(markdown)]


def _request(
    method: str,
    url: str,
    token: str,
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    status, raw = _request(
        method,
        url,
        token,
        body=body,
        content_type="application/json" if body is not None else None,
    )
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        parsed = {"message": raw.decode("utf-8", errors="replace")[:180]}
    if not isinstance(parsed, dict):
        parsed = {"message": "unexpected JSON"}
    return status, parsed


def _short_message(payload: dict) -> str:
    message = payload.get("message") or payload
    return public_error(RuntimeError(str(message)))


def upload_user_attachment(
    token: str,
    repo: str,
    repo_id: int,
    path: Path,
) -> str:
    query = urllib.parse.urlencode(
        {
            "repository_id": str(repo_id),
            "name": path.name,
            "content_type": "image/png",
        }
    )
    url = f"https://uploads.github.com/user-attachments/assets?{query}"
    status, raw = _request(
        "POST",
        url,
        token,
        body=path.read_bytes(),
        content_type="image/png",
    )
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if status not in {200, 201} or not isinstance(payload, dict):
        raise UploadError(f"user-attachments HTTP {status}")
    asset = str(payload.get("url") or payload.get("href") or "")
    if not asset.startswith("https://github.com/user-attachments/assets/"):
        raise UploadError("user-attachments response missing asset URL")
    return asset


def _repo_id(token: str, repo: str) -> int:
    status, payload = _json_request("GET", f"{API}/repos/{repo}", token)
    if status != 200 or not isinstance(payload.get("id"), int):
        raise UploadError(f"repository lookup HTTP {status}: {_short_message(payload)}")
    return int(payload["id"])


def _upload_all_attachments(
    token: str,
    repo: str,
    files: dict[str, Path],
) -> dict[str, str]:
    repo_id = _repo_id(token, repo)
    return {
        name: upload_user_attachment(token, repo, repo_id, path)
        for name, path in files.items()
    }


def _ref_sha(token: str, repo: str, branch: str) -> str | None:
    guarded_branch(branch)
    status, payload = _json_request(
        "GET",
        f"{API}/repos/{repo}/git/ref/heads/{branch}",
        token,
    )
    if status == 404:
        return None
    if status != 200:
        raise UploadError(f"read chart branch HTTP {status}: {_short_message(payload)}")
    sha = (
        ((payload.get("object") or {}).get("sha"))
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(sha, str) or not sha:
        raise UploadError("chart branch ref missing sha")
    return sha


def _create_branch(token: str, repo: str, branch: str, sha: str) -> None:
    guarded_branch(branch)
    status, payload = _json_request(
        "POST",
        f"{API}/repos/{repo}/git/refs",
        token,
        {"ref": f"refs/heads/{branch}", "sha": sha},
    )
    if status not in {201, 422}:
        raise UploadError(
            f"create chart branch HTTP {status}: {_short_message(payload)}"
        )


def _ensure_branch(token: str, repo: str, base_sha: str) -> str:
    existing = _ref_sha(token, repo, HOST_BRANCH)
    if existing:
        return existing
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise UploadError("GITHUB_SHA is not a commit sha")
    _create_branch(token, repo, HOST_BRANCH, base_sha)
    created = _ref_sha(token, repo, HOST_BRANCH)
    if not created:
        raise UploadError("chart branch was not created")
    return created


def _commit_tree_sha(token: str, repo: str, commit_sha: str) -> str:
    status, payload = _json_request(
        "GET",
        f"{API}/repos/{repo}/git/commits/{commit_sha}",
        token,
    )
    tree = (payload.get("tree") or {}).get("sha") if status == 200 else None
    if not isinstance(tree, str) or not tree:
        raise UploadError(f"read chart commit HTTP {status}: {_short_message(payload)}")
    return tree


def _create_blob(token: str, repo: str, data: bytes) -> str:
    status, payload = _json_request(
        "POST",
        f"{API}/repos/{repo}/git/blobs",
        token,
        {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"},
    )
    sha = payload.get("sha") if status == 201 else None
    if not isinstance(sha, str):
        raise UploadError(f"create blob HTTP {status}: {_short_message(payload)}")
    return sha


def _create_tree(token: str, repo: str, base_tree: str, entries: list[dict]) -> str:
    status, payload = _json_request(
        "POST",
        f"{API}/repos/{repo}/git/trees",
        token,
        {"base_tree": base_tree, "tree": entries},
    )
    sha = payload.get("sha") if status == 201 else None
    if not isinstance(sha, str):
        raise UploadError(f"create tree HTTP {status}: {_short_message(payload)}")
    return sha


def _create_commit(token: str, repo: str, message: str, tree: str, parent: str) -> str:
    author = {
        "name": "github-actions[bot]",
        "email": "41898282+github-actions[bot]@users.noreply.github.com",
    }
    status, payload = _json_request(
        "POST",
        f"{API}/repos/{repo}/git/commits",
        token,
        {
            "message": message,
            "tree": tree,
            "parents": [parent],
            "author": author,
            "committer": author,
        },
    )
    sha = payload.get("sha") if status == 201 else None
    if not isinstance(sha, str):
        raise UploadError(f"create commit HTTP {status}: {_short_message(payload)}")
    return sha


def _update_branch(token: str, repo: str, branch: str, sha: str) -> None:
    guarded_branch(branch)
    status, payload = _json_request(
        "PATCH",
        f"{API}/repos/{repo}/git/refs/heads/{branch}",
        token,
        {"sha": sha},
    )
    if status != 200:
        raise UploadError(
            f"update chart branch HTTP {status}: {_short_message(payload)}"
        )


def publish_chart_tree(
    token: str,
    repo: str,
    *,
    run_id: str,
    base_sha: str,
    files: dict[str, Path],
) -> dict[str, str]:
    """One commit on the chart host branch. Refuses every other branch."""
    parent = _ensure_branch(token, repo, base_sha)
    base_tree = _commit_tree_sha(token, repo, parent)
    entries = []
    urls: dict[str, str] = {}
    for name, path in files.items():
        object_path = chart_object_path(run_id, name)
        blob = _create_blob(token, repo, path.read_bytes())
        entries.append(
            {"path": object_path, "mode": "100644", "type": "blob", "sha": blob}
        )
        urls[name] = raw_githubusercontent_url(repo, HOST_BRANCH, object_path)
    tree = _create_tree(token, repo, base_tree, entries)
    commit = _create_commit(
        token,
        repo,
        f"ci: publish software quality kpi charts for run {run_id}\n",
        tree,
        parent,
    )
    _update_branch(token, repo, HOST_BRANCH, commit)
    return urls


def host_images(
    charts_dir: Path, names: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    errors: dict[str, str] = {}
    files: dict[str, Path] = {}
    for name in names:
        path = charts_dir / name
        if path.is_file():
            files[name] = path
        else:
            errors[name] = f"PNG not found: {name}"
    if not files:
        return {}, errors

    upload_token = os.environ.get("KPI_CHART_UPLOAD_TOKEN", "").strip()
    github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if upload_token and repo:
        try:
            urls = _upload_all_attachments(upload_token, repo, files)
            if len(urls) == len(files):
                return urls, errors
        except Exception as exc:
            print(f"user-attachments upload failed: {public_error(exc)}")

    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    base_sha = os.environ.get("GITHUB_SHA", "").strip()
    if github_token and repo and run_id and base_sha:
        try:
            return publish_chart_tree(
                github_token,
                repo,
                run_id=run_id,
                base_sha=base_sha,
                files=files,
            ), errors
        except Exception as exc:
            reason = public_error(exc)
            print(f"chart host publish failed: {reason}")
            for name in files:
                errors.setdefault(name, reason)
            return {}, errors

    reason = "no GitHub token or repository available for chart hosting"
    for name in files:
        errors.setdefault(name, reason)
    return {}, errors


def _append_summary(markdown: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    start = "<!-- kpi-charts:start -->"
    end = "<!-- kpi-charts:end -->"
    if start in markdown and end in markdown:
        body = markdown.split(start, 1)[1].split(end, 1)[0].strip()
    else:
        body = markdown.strip()
    with Path(summary).open("a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write(body)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--charts-dir", default="reports/quality/charts")
    args = parser.parse_args()
    path = Path(args.markdown)
    if not path.is_file():
        print(f"kpi chart upload skipped; missing {path}")
        return 0
    text = path.read_text(encoding="utf-8")
    names = referenced_charts(text)
    if not names:
        _append_summary(text)
        print("no chart images to host")
        return 0
    try:
        urls, errors = host_images(Path(args.charts_dir), names)
        updated = apply_image_urls(text, urls, errors)
    except Exception as exc:
        print(f"kpi chart upload failed: {public_error(exc)}")
        updated = strip_unresolved(text)
    if "kpi-chart:" in updated or "![](" in updated:
        updated = strip_unresolved(updated)
    path.write_text(updated, encoding="utf-8", newline="\n")
    _append_summary(updated)
    print(f"updated chart images in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
