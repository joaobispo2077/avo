"""Pure Shorts mapping rules and shared sound-effect metadata."""

from collections.abc import Iterable, Mapping
from copy import deepcopy


class MediaPreparationError(RuntimeError):
    """A source cannot be prepared without violating the resolved plan."""


SFX_VOLUME = {
    "chip": 0.30,
    "stamp": 0.34,
    "punch": 0.22,
    "seam": 0.20,
    "price": 0.28,
}
SFX_ASSET_KEY = {
    "chip": "sfxChip",
    "stamp": "sfxStamp",
    "punch": "sfxPunch",
    "seam": "sfxSeam",
    "price": "sfxPrice",
}
SFX_FILE_NAME = {key: f"sfx-{kind}.m4a" for kind, key in SFX_ASSET_KEY.items()}


def validate_windows(
    approved: Iterable[Mapping[str, float]],
    excluded: Iterable[Mapping[str, float]],
) -> list[tuple[float, float]]:
    windows = sorted((float(w["startSec"]), float(w["endSec"])) for w in approved)
    if not windows or any(end <= start for start, end in windows):
        raise MediaPreparationError("approved insertion windows must be non-empty")
    exclusions = [(float(w["startSec"]), float(w["endSec"])) for w in excluded]
    for start, end in windows:
        if any(max(start, x0) < min(end, x1) for x0, x1 in exclusions):
            raise MediaPreparationError(
                "approved insertion window overlaps an excluded window"
            )
    return windows


def finite_repeat_map(
    approved: Iterable[Mapping[str, float]],
    target_duration: float,
) -> list[dict[str, float]]:
    windows = validate_windows(approved, [])
    if target_duration <= 0:
        raise MediaPreparationError("insertion target duration must be positive")
    result = []
    output = 0.0
    index = 0
    while output < target_duration - 1e-9:
        start, end = windows[index % len(windows)]
        take = min(end - start, target_duration - output)
        result.append(
            {
                "outputStartSec": round(output, 6),
                "outputEndSec": round(output + take, 6),
                "sourceStartSec": start,
                "sourceEndSec": round(start + take, 6),
            }
        )
        output += take
        index += 1
    return result


def validate_source_map(
    source_map: Iterable[Mapping[str, float]],
    approved: Iterable[Mapping[str, float]],
    excluded: Iterable[Mapping[str, float]],
    target_duration: float,
) -> None:
    windows = validate_windows(approved, excluded)
    cursor = 0.0
    for segment in source_map:
        if abs(float(segment["outputStartSec"]) - cursor) > 1e-5:
            raise MediaPreparationError("insertion provenance has a gap or overlap")
        s0, s1 = float(segment["sourceStartSec"]), float(segment["sourceEndSec"])
        if not any(s0 >= w0 - 1e-9 and s1 <= w1 + 1e-9 for w0, w1 in windows):
            raise MediaPreparationError("insertion provenance escapes approved windows")
        cursor = float(segment["outputEndSec"])
    if abs(cursor - target_duration) > 1e-5:
        raise MediaPreparationError(
            "insertion provenance does not cover target duration"
        )


def motion_engine(value) -> str:
    if value not in ("hyperframes", "remotion", "code-drawn"):
        raise ValueError("motion engine must be hyperframes, remotion or code-drawn")
    return value


def resolved_motion_fields(defaults: dict, candidate: dict) -> dict:
    selected = motion_engine(
        candidate.get("motionEngine", defaults.get("motionEngine", "hyperframes"))
    )
    binding = deepcopy(candidate.get("codeDrawn", defaults.get("codeDrawn")))
    if selected == "code-drawn":
        if not isinstance(binding, dict):
            raise ValueError(
                "code-drawn Shorts require a bound canonical generated alpha asset"
            )
        return {"motionEngine": selected, "codeDrawn": binding}
    if candidate.get("codeDrawn") or (
        "motionEngine" not in candidate and binding is not None
    ):
        raise ValueError("code-drawn binding conflicts with the selected motion engine")
    return {"motionEngine": selected}
