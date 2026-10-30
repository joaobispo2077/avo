"""Evidence-bound folder proposals and bounded, versioned review edits."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import PurePosixPath
from uuid import uuid4

from avo.library.rules import reject, safe_path, validate


def initial_proposal(inventory, ref):
    groups = {}
    actions = []
    for recording in inventory["recordings"]:
        source = PurePosixPath(recording["path"])
        label, known = group_label(source)
        if label not in groups:
            groups[label] = {
                "id": uuid4().hex,
                "label": label,
                "path": label,
                "rationale": "Existing folder or filename prefix"
                if known
                else "Insufficient metadata; review required",
                "evidence": ["folder/name metadata only"],
            }
        destination = f"{label}/{source.name}" if known else recording["path"]
        status = "keep" if destination == recording["path"] and known else "move"
        if not known or recording["availability"] != "available":
            status = "unresolved"
        actions.append(
            {
                "actionId": uuid4().hex,
                "recordingId": recording["id"],
                "from": recording["path"],
                "to": destination,
                "groupId": groups[label]["id"],
                "status": status,
                "reason": groups[label]["rationale"],
                "sizeBytes": recording["observation"]["sizeBytes"],
                "durationSeconds": recording["metadata"].get("durationSeconds"),
            }
        )
    return {
        "proposalId": uuid4().hex,
        "revision": 1,
        "parent": None,
        "inventoryRef": ref,
        "groups": list(groups.values()),
        "actions": actions,
        "summary": counts(actions),
    }


def group_label(source):
    match = re.match(r"^(.+?)[-_](?:take[-_]?)?\d+$", source.stem, re.IGNORECASE)
    label = source.parent.as_posix() if source.parent.as_posix() != "." else ""
    if (
        not label
        and match
        and match[1].lower() not in {"take", "clip", "video", "dji", "img"}
    ):
        label = match[1]
    return label or "needs-review", bool(label)


def counts(actions):
    return {
        "total": len(actions),
        **{
            key: sum(a["status"] == key for a in actions)
            for key in ("move", "keep", "exclude", "unresolved", "blocked")
        },
    }


def checked_destinations(root, proposal):
    targets = {}
    for action in proposal["actions"]:
        safe_path(root, action["from"])
        if action["to"] != action["from"]:
            safe_path(root, action["to"])
        if action["status"] != "move":
            continue
        targets.setdefault(action["to"].casefold(), []).append(action)
    for actions in targets.values():
        if len(actions) > 1:
            for action in actions:
                action.update(
                    status="blocked", reason="Conflicting proposed destination"
                )
    proposal["summary"] = counts(proposal["actions"])
    return proposal


def apply_edits(root, original, ref, request):
    validate("edits", request)
    if (
        request["baseProposalId"] != original["proposalId"]
        or request["baseRevision"] != original["revision"]
        or request["baseProposalHash"] != ref["sha256"]
    ):
        reject("LIB_STALE_PROPOSAL", "The displayed proposal has changed", "stale")
    result = deepcopy(original)
    result.update(revision=original["revision"] + 1, parent=ref)
    groups = {item["id"]: item for item in result["groups"]}
    actions = {item["recordingId"]: item for item in result["actions"]}
    for edit in request["edits"]:
        if edit["type"] == "rename-group":
            _rename_group(root, edit, groups, actions)
        else:
            _edit_action(edit, actions, groups)
    return checked_destinations(root, result)


def _rename_group(root, edit, groups, actions):
    group = groups.get(edit.get("groupId"))
    if not group or not edit.get("label"):
        reject(
            "LIB_INVALID_REQUEST", "Choose an existing group and a valid folder name"
        )
    safe_path(root, edit["label"])
    group.update(label=edit["label"], path=edit["label"])
    for action in actions.values():
        explicitly_kept = (
            action["status"] == "keep" and action["reason"] == "Creator-requested keep"
        )
        if (
            action["groupId"] == group["id"]
            and action["status"] != "exclude"
            and not explicitly_kept
        ):
            action.update(
                to=f"{group['path']}/{PurePosixPath(action['from']).name}",
                status="move",
            )


def _edit_action(edit, actions, groups):
    action = actions.get(edit.get("recordingId"))
    if action is None:
        reject("LIB_INVALID_REQUEST", "Unknown recording")
    kind = edit["type"]
    if kind in {"exclude-recording", "keep-recording"}:
        action.update(
            status="exclude" if kind.startswith("exclude") else "keep",
            to=action["from"],
            reason="Creator-requested keep"
            if kind.startswith("keep")
            else "Creator-requested exclusion",
        )
        return
    group = groups.get(edit.get("groupId"))
    if group is None:
        reject("LIB_INVALID_REQUEST", "Unknown destination group")
    action.update(
        groupId=group["id"],
        to=f"{group['path']}/{PurePosixPath(action['from']).name}",
        status="move",
        reason="Creator-requested assignment",
    )
