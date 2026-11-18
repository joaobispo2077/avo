"""Resolve selected sound anchors from canonical camera metadata, without execution."""

from fractions import Fraction

from .camera import _behavior, _encoded
from .contracts import content_hash, validate_document
from .sound_fitting import SoundPlanningError


def _owning_component(anchor, cue, animation):
    references = {
        value
        for value in (
            cue.get("componentRef"),
            (cue.get("contentRef") or {}).get("componentId"),
        )
        if value is not None
    }
    if references != {anchor["componentId"]}:
        raise SoundPlanningError(
            "Camera anchor needs the exact unambiguous owning cue component"
        )
    matches = [
        component
        for component in (animation or {}).get("components", [])
        if component["componentId"] == anchor["componentId"]
    ]
    if len(matches) != 1:
        raise SoundPlanningError(
            "Canonical camera anchor component is unavailable or ambiguous"
        )
    return matches[0]


def _camera_wrapper(anchor, cue, animation):
    component = _owning_component(anchor, cue, animation)
    wrapper = (component.get("extensions") or {}).get("editingCraft")
    validate_document(wrapper, "avo.animation.schema.json#/$defs/editingCraft")
    camera = wrapper["camera"]
    _behavior(_encoded(camera))
    if camera["targetLayerId"] != cue.get("targetLayerId"):
        raise SoundPlanningError(
            "Camera anchor target differs from its owning picture layer"
        )
    if wrapper.get("sourceSha256") != anchor["sourceSha256"]:
        raise SoundPlanningError("Camera anchor source changed")
    return wrapper


def sound_phase(intent, part, animation=None):
    anchor = intent.get("cameraAnchor")
    if anchor is None:
        return Fraction(str(intent.get("phase", 0)))
    validate_document(anchor, "avo.sound-selection.schema.json#/$defs/cameraAnchor")
    wrapper = _camera_wrapper(anchor, part.get("cue") or {}, animation)
    camera = wrapper["camera"]
    digest = content_hash(
        {"behavior": camera, "geometry": wrapper.get("sourceGeometry")}
    )
    if digest != anchor["pathHash"]:
        raise SoundPlanningError("Camera anchor path changed")
    if anchor["nodeIndex"] >= len(camera["nodes"]):
        raise SoundPlanningError("Camera anchor node is unavailable")
    return Fraction(str(camera["nodes"][anchor["nodeIndex"]]["phase"]))
