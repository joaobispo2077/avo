"""Pure opt-in cutting policy resolution with non-overridable protections."""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from avo.settings import resolve_scoped_settings, stable_settings_hash

from .cutting_profiles import INTENSITIES, CutProfile, get_profile


class CuttingPolicyError(ValueError):
    """Invalid configuration must fail before a source selection can change."""


_DEFAULTS = {
    "enabled": False,
    "family": None,
    "intensity": "balanced",
    "guards": {"beforeMs": 120, "afterMs": 180},
    "language": None,
    "purpose": None,
    "notes": [],
    "protectedEvents": [],
    "runtimeRefs": {},
    "sections": {},
}


def _integer_at_least(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _source_range(event: dict) -> dict:
    interval = event.get("sourceRange")
    if interval is None:
        interval = {
            "sourceId": event.pop("sourceId", None),
            "startTicks": event.pop("startMs", None),
            "endTicksExclusive": event.pop("endMs", None),
            "timebase": {"num": 1, "den": 1000},
        }
    if not isinstance(interval, dict):
        raise CuttingPolicyError("protected sourceRange must be an object")
    start, end = interval.get("startTicks"), interval.get("endTicksExclusive")
    if not all(
        (
            _integer_at_least(start, 0),
            _integer_at_least(end, 1),
            bool(interval.get("sourceId")),
        )
    ):
        raise CuttingPolicyError("protected event requires a positive source interval")
    if end <= start:
        raise CuttingPolicyError("protected event requires a positive source interval")
    basis = interval.get("timebase")
    if not isinstance(basis, dict) or not all(
        _integer_at_least(basis.get(key), 1) for key in ("num", "den")
    ):
        raise CuttingPolicyError(
            "protected sourceRange requires a positive rational timebase"
        )
    return interval


def normalize_protected_events(events: Iterable[Mapping[str, Any]]) -> tuple[dict, ...]:
    """Union source protections; contradictory definitions cannot erase a hold."""
    normalized: dict[str, dict] = {}
    for source in events:
        event = deepcopy(dict(source))
        identity = event.get("eventId")
        if not isinstance(identity, str) or not identity.strip():
            raise CuttingPolicyError("protected event requires eventId")
        event["sourceRange"] = _source_range(event)
        minimum = event.get("minimumDurationMs")
        if minimum is not None and not _integer_at_least(minimum, 0):
            raise CuttingPolicyError(
                "protected minimum duration must be nonnegative milliseconds"
            )
        if identity in normalized and event != normalized[identity]:
            raise CuttingPolicyError(f"conflicting protected event: {identity}")
        normalized[identity] = event
    return tuple(normalized[key] for key in sorted(normalized))


@dataclass(frozen=True)
class CuttingPolicy:
    enabled: bool
    effective: dict
    sources: dict[str, str]
    policy_hash: str
    profile: CutProfile | None
    protections: tuple[dict, ...]

    def payload(self) -> dict:
        return deepcopy(
            {
                "effective": self.effective,
                "sources": self.sources,
                "policyHash": self.policy_hash,
                "profile": self.profile.payload() if self.profile else None,
                "protectedEvents": list(self.protections),
            }
        )


def _validate_guards(guards: Any) -> None:
    if not isinstance(guards, dict) or set(guards) != {"beforeMs", "afterMs"}:
        raise CuttingPolicyError("cutting guards require beforeMs and afterMs")
    for key, floor in (("beforeMs", 120), ("afterMs", 180)):
        value = guards[key]
        if not _integer_at_least(value, floor):
            raise CuttingPolicyError(f"cutting guard {key} cannot be below {floor} ms")


def _validate_context(values: dict) -> None:
    _validate_sections(values["sections"])
    if not isinstance(values["runtimeRefs"], dict):
        raise CuttingPolicyError("cutting.runtimeRefs must be an object")
    for name in ("language", "purpose"):
        if values[name] is not None and (
            not isinstance(values[name], str) or not values[name].strip()
        ):
            raise CuttingPolicyError(f"cutting.{name} must be non-empty text or null")
    if not isinstance(values["notes"], list) or not all(
        isinstance(v, str) for v in values["notes"]
    ):
        raise CuttingPolicyError("cutting.notes must be a string list")


def _validate_sections(sections) -> None:
    if not isinstance(sections, dict) or not all(
        isinstance(key, str) and key and isinstance(value, dict)
        for key, value in sections.items()
    ):
        raise CuttingPolicyError(
            "cutting.sections must map section identifiers to objects"
        )


def _validate_settings(values: dict) -> CutProfile | None:
    if set(values) - set(_DEFAULTS):
        raise CuttingPolicyError("unknown cutting setting")
    if not isinstance(values["enabled"], bool):
        raise CuttingPolicyError("cutting.enabled must be boolean")
    if values["intensity"] not in INTENSITIES:
        raise CuttingPolicyError("unknown cutting intensity")
    _validate_guards(values["guards"])
    _validate_context(values)
    if not values["enabled"] and values["family"] is None:
        return None
    try:
        return get_profile(values["family"], values["intensity"])
    except (ValueError, TypeError) as exc:
        raise CuttingPolicyError(str(exc)) from exc


def _declared_protections(settings: dict) -> list:
    """Source holds survive pacing scopes and every weaker declaration."""
    sections = settings.get("sections", {})
    _validate_sections(sections)
    events = []
    for declaration in (settings, *sections.values()):
        declared = declaration.get("protectedEvents", [])
        if not isinstance(declared, list):
            raise CuttingPolicyError("protectedEvents must be a list")
        events.extend(declared)
    return events


def resolve_cutting_policy(
    *,
    global_settings=None,
    provider_settings=None,
    project_settings=None,
    run_settings=None,
    section_settings=None,
    protected_events=(),
    manual_locks=(),
) -> CuttingPolicy:
    scopes = list(
        zip(
            ("global", "provider", "project", "run", "section"),
            (
                global_settings,
                provider_settings,
                project_settings,
                run_settings,
                section_settings,
            ),
        )
    )
    resolved = resolve_scoped_settings(defaults=_DEFAULTS, scopes=scopes)
    values = resolved.values
    profile = _validate_settings(values)
    protections = list(protected_events)
    for _, settings in scopes:
        if settings:
            protections.extend(_declared_protections(settings))
    protections.extend({**dict(lock), "kind": "manual-lock"} for lock in manual_locks)
    protected = normalize_protected_events(protections)
    values["protectedEvents"] = list(protected)
    policy_hash = stable_settings_hash(
        {
            "effective": values,
            "sources": resolved.sources,
            "profile": profile.payload() if profile else None,
        }
    )
    return CuttingPolicy(
        values["enabled"], values, resolved.sources, policy_hash, profile, protected
    )


def resolve_section_policy(
    base: CuttingPolicy, section_id: str | None
) -> CuttingPolicy:
    """Apply section pacing without weakening already resolved source safeguards."""
    override = base.effective["sections"].get(section_id)
    if not override:
        return base
    configured = deepcopy(override)
    if "sections" in configured:
        raise CuttingPolicyError("section overrides cannot define nested sections")
    guards = configured.get("guards", {})
    _validate_guards({**base.effective["guards"], **guards})
    configured["guards"] = {
        key: max(value, guards.get(key, value))
        for key, value in base.effective["guards"].items()
    }
    section = resolve_cutting_policy(
        run_settings=base.effective,
        section_settings=configured,
        protected_events=base.protections,
    )
    sources = {
        key: "section" if origin == "section" else base.sources.get(key, origin)
        for key, origin in section.sources.items()
    }
    for key, value in base.effective["guards"].items():
        if section.effective["guards"][key] == value:
            path = "guards." + key
            sources[path] = base.sources.get(path, base.sources["guards"])
    policy_hash = stable_settings_hash(
        {
            "effective": section.effective,
            "sources": sources,
            "profile": section.profile.payload() if section.profile else None,
        }
    )
    return CuttingPolicy(
        section.enabled,
        section.effective,
        sources,
        policy_hash,
        section.profile,
        section.protections,
    )


def pause_retention(
    duration_ms: int,
    policy: CuttingPolicy,
    *,
    confirmed_dispensable=False,
    protected=False,
    rounding_allowance_ms: int = 0,
) -> dict:
    """Report a pacing preference; this function never authorizes a CMap edit."""
    if not _integer_at_least(duration_ms, 0):
        raise CuttingPolicyError("pause duration must be nonnegative milliseconds")
    if not _integer_at_least(rounding_allowance_ms, 0):
        raise CuttingPolicyError("rounding allowance must be nonnegative milliseconds")
    profile = policy.profile
    band = profile.pause_band(duration_ms) if profile else None
    target = profile.retention_target(band) if profile else None
    retained = duration_ms
    floor = sum(policy.effective["guards"].values()) + rounding_allowance_ms
    eligible = all(
        (policy.enabled, confirmed_dispensable, not protected, target is not None)
    )
    if eligible:
        retained = min(duration_ms, max(target, floor))
    return {
        "band": band,
        "action": "shorten" if retained < duration_ms else "keep",
        "originalMs": duration_ms,
        "requestedTargetMs": target,
        "retainedMs": retained,
        "guardLimited": bool(eligible and floor > target),
        "protected": bool(protected),
        "policyHash": policy.policy_hash,
        "calibrationStatus": profile.calibration_status if profile else "disabled",
    }
