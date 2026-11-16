"""Recognize explicit disabled Resolve effects without evaluating their payloads."""


def inactive_effect(node):
    if not isinstance(node, dict):
        return False
    metadata = node.get("metadata", {})
    evidence = metadata.get("Resolve_OTIO", {}) if isinstance(metadata, dict) else {}
    if not isinstance(evidence, dict):
        return False
    name = evidence.get("Effect Name")
    identity = (
        node.get("OTIO_SCHEMA") == "Effect.1"
        and node.get("effect_name") == "Resolve Effect"
    )
    return identity and _disabled_named(node, evidence, name)


def _disabled_named(node, evidence, name):
    return (
        evidence.get("Enabled") is False
        and node.get("enabled", False) is False
        and isinstance(name, str)
        and 0 < len(name) <= 240
        and not any(ord(char) < 32 for char in name)
    )


def inactive_clip(node):
    effects = _clip_effects(node)
    return bool(effects) and all(inactive_effect(effect) for effect in effects)


def _clip_effects(node):
    effects = node.get("effects", [])
    if node.get("OTIO_SCHEMA") not in {"Clip.1", "Clip.2"} or not isinstance(
        effects, list
    ):
        return []
    return effects


def collect_inactive(selected, pointer):
    from . import otio_import

    records, owners = [], set()
    for location, node, content, _ in otio_import._walk(selected, pointer):
        if not content:
            continue
        if inactive_clip(node):
            owners.add(location)
        for index, effect in enumerate(_clip_effects(node)):
            if not inactive_effect(effect):
                continue
            if len(records) >= otio_import.MAX_REPORT_ITEMS:
                raise otio_import.ImportError(
                    "OTIO_INPUT_LIMIT", "Too many inactive effects"
                )
            records.append(
                {
                    "pointer": otio_import._pointer(
                        otio_import._pointer(location, "effects"), index
                    ),
                    "ownerPointer": location,
                    "name": effect["metadata"]["Resolve_OTIO"]["Effect Name"],
                    "enabled": False,
                    "evidenceOrigin": "export",
                }
            )
    return records, owners
