"""Publish explicitly selected reference measurements for later inspection."""

import hashlib
import os
from fractions import Fraction
from pathlib import Path
from tempfile import NamedTemporaryFile

from avo.editing_craft import validate_editing_craft_selection
from avo.reference_analysis import SCHEMA

from .contracts import content_hash, file_fingerprint, validate_document
from .motion_authoring import MotionAuthoringService
from .store import timeline_writer, write_immutable_json

CLIP_FACTS = ("source", "sourceRange", "aspects")
DEFAULT_BUDGET = {"maxClips": 10, "maxTotalSeconds": 300}
MAX_SHEET_BYTES = 1024 * 1024


def _duration(clip):
    scope = clip["sourceRange"]
    base = scope["timebase"]
    duration = (scope["endTicks"] - scope["startTicks"]) * Fraction(
        base["num"], base["den"]
    )
    if not 0 < duration <= 30:
        raise ValueError(
            "Each reference range must cover up to 30 seconds on its source clock"
        )
    return duration


def _validate_budget(request):
    clips = request["clips"]
    budget = request.get("budget", DEFAULT_BUDGET)
    if (
        len(clips) > budget["maxClips"]
        or sum(map(_duration, clips)) > budget["maxTotalSeconds"]
    ):
        raise ValueError("Reference selection exceeds its explicit time or clip budget")
    if len({clip["clipId"] for clip in clips}) != len(clips):
        raise ValueError("Reference selections require unique clip identities")


def _local_path(locator):
    if not Path(locator).is_absolute() or locator.startswith(("//", "\\\\")):
        raise ValueError("Reference analysis requires explicit local paths")
    return Path(locator).resolve()


def _check_source(path, expected):
    actual = file_fingerprint(path)
    if any(actual[key] != expected[key] for key in ("sha256", "sizeBytes")):
        raise ValueError("Reference source bytes differ from the selected clip")


def _validate_clip_result(clip, observation, sheet):
    validate_document(observation, SCHEMA + "#/$defs/referenceObservation")
    expected = {
        key: value for key, value in observation.items() if key != "analysisHash"
    }
    if observation["analysisHash"] != content_hash(expected) or any(
        observation["request"][key] != clip[key] for key in CLIP_FACTS
    ):
        raise ValueError("Reference observations differ from the selected clip")
    if (
        not isinstance(sheet, bytes)
        or not sheet.startswith(b"\x89PNG\r\n\x1a\n")
        or len(sheet) > MAX_SHEET_BYTES
    ):
        raise ValueError("Reference contact sheet needs bounded PNG bytes")


def _path(workspace, name):
    target = workspace.raw_dir / name
    if not target.resolve().is_relative_to(workspace.raw_dir.resolve()):
        raise ValueError("Reference observation output escapes the project")
    return target


def _save_sheet(workspace, sheet):
    digest = hashlib.sha256(sheet).hexdigest()
    name = f"edit/motion/references/sheets/{digest}.png"
    path = _path(workspace, name)
    if path.exists():
        _check_source(path, {"sha256": digest, "sizeBytes": len(sheet)})
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        _publish_sheet(path, sheet)
    return {"locator": name, "sha256": digest}


def _publish_sheet(path, sheet):
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(sheet)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _measure_selected_clips(request, analyze, python):
    paths = [_local_path(clip["locator"]) for clip in request["clips"]]
    for path, clip in zip(paths, request["clips"], strict=True):
        _check_source(path, clip["source"])
    measured = []
    for path, clip in zip(paths, request["clips"], strict=True):
        observation, sheet = analyze(path, clip, python)
        _validate_clip_result(clip, observation, sheet)
        measured.append((path, clip, observation, sheet))
    return measured


def _publish_observations(workspace, request, measured):
    for path, clip, _, _ in measured:
        _check_source(path, clip["source"])
    rows = [
        {
            "clipId": clip["clipId"],
            "observation": observation,
            "contactSheet": _save_sheet(workspace, sheet),
        }
        for _, clip, observation, sheet in measured
    ]
    record = {
        "request": request,
        "clips": rows,
        "provider": workspace.project["provider"],
        "videoId": workspace.video_id,
        "use": "inspection-only",
    }
    name = f"edit/motion/references/{content_hash(record)}.json"
    path = write_immutable_json(_path(workspace, name), record)
    return {
        "status": "observed",
        "review": "required",
        "observationRef": {"locator": name, "sha256": file_fingerprint(path)["sha256"]},
        "clips": [
            {
                "clipId": row["clipId"],
                "coverage": row["observation"]["coverage"],
                "contactSheet": row["contactSheet"],
            }
            for row in rows
        ],
    }


def analyze_reference(workspace, request, analyze):
    """Inspect the exact requested local sources and leave editorial ownership intact."""
    validate_document(request, SCHEMA + "#/$defs/referenceAnalyzeRequest")
    choice = validate_editing_craft_selection(request["selection"])["effective"]
    if not choice["referenceAnalysis"]["enabled"]:
        raise ValueError("Reference analysis requires explicit selected options")
    _validate_budget(request)
    python = _local_path(request["runtimePython"])
    authoring = MotionAuthoringService(workspace)
    authoring._check_heads(request["expectedBasis"])
    measured = _measure_selected_clips(request, analyze, python)
    with timeline_writer(workspace.timeline_dir):
        authoring._check_heads(request["expectedBasis"])
        return _publish_observations(workspace, request, measured)
