"""Project checked asset-local event ranges onto the frozen program clock."""


def _projected(binding, operation):
    source = operation["parameters"]["sourceRange"]
    local = binding.get("assetFrameRange") or {}
    first, last = local.get("startFrame"), local.get("endFrameExclusive")
    if type(first) is not int or type(last) is not int:
        return None
    if not source["startFrame"] <= first < last <= source["endFrameExclusive"]:
        return None
    origin = operation["outputRange"]["startFrame"] - source["startFrame"]
    return {"startFrame": first + origin, "endFrameExclusive": last + origin}


def bound_visual_event(event, generated):
    """Only already inspected/admitted generated records may supply bindings."""
    matches = []
    for asset in (generated or {}).values():
        operation = asset["operation"]
        if operation["kind"] not in {"overlay-video", "generated-clip"}:
            continue
        bindings = asset["record"].get("parameters", {}).get("eventBindings") or []
        for binding in bindings:
            if (
                binding.get("eventId") == event.get("eventId")
                and _projected(binding, operation) is not None
            ):
                matches.append((binding, operation))
    if len(matches) != 1:
        return False
    binding, operation = matches[0]
    if binding.get("role") != event.get("role"):
        return False
    return _projected(binding, operation) == event.get("visibleRange")
