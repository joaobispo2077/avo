"""Bind reviewed asset choices to motion selections and preflight."""

import hashlib
import json
from copy import deepcopy

from .asset_review import (
    SCHEMA,
    SOURCE_FIELDS,
    _option_path,
    _option_state,
    _required_asset,
    _root_paths,
)
from .contracts import content_hash, file_fingerprint, validate_document
from .reference_observation import _path


def _read_round(workspace, reference):
    validate_document(reference, SCHEMA + "roundRef")
    path = _path(workspace, reference["locator"])
    with path.open("rb") as stream:
        raw = stream.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024 or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("Asset review round bytes changed or exceed the review budget")
    record = json.loads(raw)
    if not isinstance(record, dict) or content_hash(record) != path.stem:
        raise ValueError("Asset review round identity changed")
    if (record.get("provider"), record.get("videoId")) != (
        workspace.project["provider"],
        workspace.video_id,
    ):
        raise ValueError("Asset review belongs to another project")
    validate_document(record, SCHEMA + "roundRecord")
    return record


def _check_option_identity(record, option):
    if option["state"] != "ready-for-review":
        raise ValueError("Selected asset option is unresolved")
    request = record["request"]
    entries = [
        row for row in request["options"] if row["optionId"] == option["optionId"]
    ]
    if (
        len(entries) != 1
        or _option_state(record["need"], entries[0]) != "ready-for-review"
    ):
        raise ValueError("Selected asset option differs from its inspected need")
    option_source = option["source"]
    if any(option_source[key] != entries[0][key] for key in SOURCE_FIELDS):
        raise ValueError("Selected asset option differs from its inspected source")
    return option_source


def _require_current_option(record, option):
    option_source = _check_option_identity(record, option)
    source = _option_path(_root_paths(record["request"]["roots"]), option_source)
    if not source.is_file() or source.stat().st_size != option_source["sizeBytes"]:
        raise ValueError("Selected asset bytes changed or are unavailable")
    if file_fingerprint(source)["sha256"] != option_source["sha256"]:
        raise ValueError("Selected asset bytes changed or are unavailable")
    return source


def _selected_round(authoring, selection, reference):
    record = _read_round(authoring.workspace, reference)
    request = record["request"]
    if (
        request["proposalHash"] != selection["proposalHash"]
        or request["expectedBasis"] != selection["expectedBasis"]
    ):
        raise ValueError("Asset review differs from the selected proposal or basis")
    if record["need"] != _required_asset(authoring, request):
        raise ValueError("Asset review need changed")
    return record


def _verify_sheet(workspace, reference):
    sheet = _path(workspace, reference["locator"])
    if not sheet.is_file() or sheet.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Asset comparison sheet is unavailable")
    if file_fingerprint(sheet)["sha256"] != reference["sha256"]:
        raise ValueError("Asset comparison sheet bytes changed")


def resolve_asset_choice(authoring, selection, choice):
    validate_document(choice, SCHEMA + "choice")
    record = _selected_round(authoring, selection, choice["roundRef"])
    request = record["request"]
    number = choice.get("optionNumber")
    option = next(
        (option for option in record["options"] if option["number"] == number), None
    )
    if number is not None and option is None:
        raise ValueError("Select an option from the exact numbered asset review")
    evidence = {
        "choice": choice,
        "itemId": request["itemId"],
        "assetIndex": request["assetIndex"],
        "option": option,
        "contactSheet": record["contactSheet"],
    }
    validate_document(evidence, SCHEMA + "choiceEvidence")
    _verify_sheet(authoring.workspace, evidence["contactSheet"])
    if choice["disposition"] != "reject":
        _require_current_option(record, option)
    return evidence


def resolve_asset_choices(authoring, request, previous):
    selector = request["selection"]
    requested = selector.get("assetChoices")
    if requested is None:
        if previous.get("proposalRef", {}).get("sha256") != selector["proposalHash"]:
            return {}
        current = (previous.get("decision") or {}).get("assetChoices", [])
        return {"assetChoices": deepcopy(current)} if current else {}
    scope = {
        "proposalHash": selector["proposalHash"],
        "expectedBasis": request["expectedBasis"],
    }
    choices = [resolve_asset_choice(authoring, scope, choice) for choice in requested]
    identities = [(row["itemId"], row["assetIndex"]) for row in choices]
    if len(set(identities)) != len(identities):
        raise ValueError("Select one disposition for each contextual asset need")
    return {
        "assetChoices": sorted(
            choices, key=lambda row: (row["itemId"], row["assetIndex"])
        )
    }


def attach_asset_choices(proposal, decision):
    reviewed = {
        (row["itemId"], row["assetIndex"]): row
        for row in decision.get("assetChoices", [])
    }
    for item in proposal.get("items", []):
        for index, asset in enumerate(item.get("assets", [])):
            review = reviewed.get((item["itemId"], index))
            if review is not None:
                asset["review"] = review


def verify_application_assets(authoring, shown):
    decision = shown["decision"]
    selected = {
        row["itemId"] for row in decision["dispositions"] if row["status"] == "selected"
    }
    scope = {
        "proposalHash": shown["proposalRef"]["sha256"],
        "expectedBasis": shown["proposal"]["basisHeads"],
    }
    for evidence in decision.get("assetChoices", []):
        if (
            evidence["itemId"] not in selected
            or evidence["choice"]["disposition"] == "reject"
        ):
            continue
        if resolve_asset_choice(authoring, scope, evidence["choice"]) != evidence:
            raise ValueError("Selected asset evidence changed before application")
