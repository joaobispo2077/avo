"""Code-drawn source identities at canonical schema and authoring boundaries."""

from __future__ import annotations

import copy
import json

import pytest

from avo.motion import MotionError, scaffold_code_drawn
from avo.timeline.animation import AnimationError, AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import (
    ContractError,
    canonical_json_bytes,
    file_fingerprint,
    validate_document,
)
from avo.timeline.tracks import TracksService
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_tracks_service import canonical_tracks
from tests.test_video_animation_schema import strategy_document

SHA = "a" * 64


def canonical_drawing_reference(workspace, instance_id="drawing-one"):
    destination = (
        workspace.raw_dir
        / "edit"
        / "derived"
        / "components"
        / instance_id
        / "source-r0001"
    )
    scaffold_code_drawn(
        destination,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=9,
        background="transparent",
    )
    composition = destination / "composition.json"
    return {
        "engine": "code-drawn",
        "instanceId": instance_id,
        "manifestRef": {
            "path": composition.relative_to(workspace.raw_dir).as_posix(),
            "sha256": file_fingerprint(composition)["sha256"],
        },
    }


def code_drawn_strategy(reference):
    value = strategy()
    value["framework"] = "code-drawn"
    component = value["components"][0]
    component.pop("providerPatternRef")
    component["extensions"] = {
        "codeDrawn": {
            "instanceId": reference["instanceId"],
            "manifestRef": copy.deepcopy(reference["manifestRef"]),
        }
    }
    return value


def _schema_strategy():
    document = strategy_document()
    value = document["revisions"][0]["strategy"]
    value["framework"] = "code-drawn"
    component = value["components"][0]
    component.pop("providerPatternRef")
    component["extensions"] = {
        "codeDrawn": {
            "instanceId": "drawing-one",
            "manifestRef": {
                "path": "edit/derived/components/drawing-one/source-r0001/composition.json",
                "sha256": SHA,
            },
        }
    }
    return document, value, component["extensions"]["codeDrawn"]


