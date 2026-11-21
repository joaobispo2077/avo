"""Bind contextual asset options to one exact project motion need."""

from copy import deepcopy
from pathlib import Path, PureWindowsPath

from .contracts import content_hash, file_fingerprint, validate_document
from .reference_observation import _path, _save_sheet
from .store import timeline_writer, write_immutable_json

SCHEMA = "avo.asset-review.schema.json#/$defs/"
SOURCE_FIELDS = ("rootId", "relativePath", "sha256", "sizeBytes")
REVIEWABLE_RIGHTS = {"owned", "licensed", "permission-granted", "public-domain"}


def _root_paths(roots):
    locations = {}
    for root in roots:
        validate_document(root, SCHEMA + "root")
        location = Path(root["locator"])
        if not location.is_absolute() or root["locator"].startswith(("//", "\\\\")):
            raise ValueError("Asset review needs explicitly declared local folders")
        if root["rootId"] in locations:
            raise ValueError("Asset review folder identities must be unique")
        locations[root["rootId"]] = location.resolve()
    return locations


def _option_path(roots, source):
    root = roots.get(source["rootId"])
    if root is None:
        raise ValueError("Asset option refers to an undeclared folder")
    relative = PureWindowsPath(source["relativePath"])
    if relative.anchor or any(part == ".." or ":" in part for part in relative.parts):
        raise ValueError("Asset option escapes its declared folder")
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("Asset option escapes its declared folder")
    return target


def _normalized(value):
    return " ".join(value.casefold().split())


def _option_state(need, option):
    for key in ("kind", "subject", "supplier"):
        if _normalized(need[key]) != _normalized(option[key]):
            return f"{key}-mismatch"
    rights = option["rights"]
    if rights["state"] not in REVIEWABLE_RIGHTS or not rights.get("evidence"):
        return "rights-unverified"
    return "ready-for-review"


def inspect_asset_options(
    need, roots, options, background, render, *, background_source=None
):
    """Evaluate only explicit options and keep inspection independent of admission."""
    folders = _root_paths(roots)
    if not all(need.get(key) for key in ("kind", "subject", "supplier")):
        raise ValueError(
            "This asset need requires a type, subject and responsible supplier"
        )
    prepared = []
    seen = set()
    for number, option in enumerate(
        sorted(options, key=lambda row: row["optionId"]), 1
    ):
        validate_document(option, SCHEMA + "option")
        identifier = option["optionId"]
        if identifier in seen:
            raise ValueError("Asset options must have unique identities")
        seen.add(identifier)
        source = {key: option[key] for key in SOURCE_FIELDS}
        path = _option_path(folders, source)
        row = {
            key: deepcopy(option[key])
            for key in ("optionId", "kind", "subject", "supplier", "rights")
        }
        row.update(number=number, state=_option_state(need, option), source=source)
        prepared.append((row, path if row["state"] == "ready-for-review" else None))
    if background_source is None:
        return render(prepared, background)
    validate_document(background_source, SCHEMA + "source")
    context = (_option_path(folders, background_source), background_source)
    return render(prepared, background, context=context)


def _required_asset(authoring, request):
    # Proposal bytes and their hash are resolved by the existing motion authoring store.
    proposal, _ = authoring._load("proposals", request["proposalHash"], "proposal")
    if proposal["basisHeads"] != request["expectedBasis"]:
        raise ValueError("Asset selection requires a proposal on the requested basis")
    matches = [
        item for item in proposal["items"] if item["itemId"] == request["itemId"]
    ]
    if len(matches) != 1:
        raise ValueError("Asset selection requires one exact motion item")
    (item,) = matches
    assets = item.get("assets", [])
    if request["assetIndex"] >= len(assets):
        raise ValueError(
            "Asset selection requires a declared need on the selected item"
        )
    return assets[request["assetIndex"]]


def open_asset_round(authoring, request, render):
    """Publish numbered local options without acquiring or applying an asset."""
    validate_document(request, SCHEMA + "roundRequest")
    workspace = authoring.workspace
    authoring._check_heads(request["expectedBasis"])
    need = _required_asset(authoring, request)
    root_status = {
        identity: "available" if path.is_dir() else "unavailable"
        for identity, path in _root_paths(request["roots"]).items()
    }
    options, sheet = inspect_asset_options(
        need,
        request["roots"],
        request["options"],
        request["background"],
        render,
        background_source=request.get("backgroundSource"),
    )
    for option in options:
        validate_document(option, SCHEMA + "optionEvidence")
    if not sheet.startswith(b"\x89PNG\r\n\x1a\n") or len(sheet) > 2 * 1024 * 1024:
        raise ValueError("Asset review needs a bounded PNG comparison sheet")
    with timeline_writer(workspace.timeline_dir):
        authoring._check_heads(request["expectedBasis"])
        record = {
            "provider": workspace.project["provider"],
            "videoId": workspace.video_id,
            "request": request,
            "need": need,
            "rootStatus": root_status,
            "options": options,
            "contactSheet": _save_sheet(workspace, sheet, area="assets"),
        }
        validate_document(record, SCHEMA + "roundRecord")
        name = f"edit/motion/assets/{content_hash(record)}.json"
        stored = write_immutable_json(_path(workspace, name), record)
    return {
        "status": "review-required",
        "roundRef": {"locator": name, "sha256": file_fingerprint(stored)["sha256"]},
        "itemId": request["itemId"],
        "assetIndex": request["assetIndex"],
        "need": need,
        "rootStatus": root_status,
        "options": options,
        "contactSheet": record["contactSheet"],
    }
