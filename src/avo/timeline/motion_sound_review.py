"""Pure sound links for the derived motion map; no media or publication authority."""

from copy import deepcopy

from .contracts import content_hash, validate_document
from .sound_choices import _sound_document
from .sound_tracks import _sound_layers


def sound_review_context(value, gaps):
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or set(value) != {"proposal", "proposalRef"}:
            raise ValueError("Sound context needs an exact proposal and reference")
        _sound_document(value["proposal"], "proposal")
        validate_document(
            value["proposalRef"], "avo.motion-proposal.schema.json#/$defs/ref"
        )
        proposal, reference = value["proposal"], value["proposalRef"]
        if (
            reference["path"]
            != f"edit/motion/sound/proposals/{reference['sha256']}.json"
        ):
            raise ValueError("Sound context reference has the wrong typed path")
        if proposal["proposalHash"] != content_hash(
            {key: item for key, item in proposal.items() if key != "proposalHash"}
        ):
            raise ValueError("Sound context proposal identity changed")
    except (ValueError, TypeError, KeyError) as error:
        gaps.append({"kind": "sound-proposal-unavailable", "detail": str(error)})
        return None
    return deepcopy(value)


def add_sound_groups(groups, context):
    for record in (context or {}).get("proposal", {}).get("opportunities", []):
        groups.setdefault(
            record["itemId"],
            {
                "proposals": [
                    {
                        "itemId": record["itemId"],
                        "concept": record["intent"]["purpose"],
                        "disposition": "proposed",
                    }
                ],
                "cues": [],
            },
        )


def _selection(layer):
    selected = layer["provenance"]["soundSelection"]
    choice = selected["choice"]
    entry = choice["sourceEntry"]
    return {
        "eventId": choice["eventId"],
        "layerId": layer["layerId"],
        "cueId": selected["cueId"],
        "visualCueId": choice["fit"]["opportunity"]["cueId"],
        "entryId": entry["entryId"],
        "libraryId": entry["libraryId"],
        "relativePath": entry["relativePath"],
        "role": choice["fit"]["opportunity"]["role"],
        "muted": layer.get("mute", False),
        "gainDb": layer.get("gainDb", 0),
        "proposalRef": deepcopy(selected["proposalRef"]),
        "applicationRef": deepcopy(selected["applicationRef"]),
        "acceptance": choice["acceptance"],
        "evidenceType": "authored-metadata",
    }


def enrich_sound_items(items, tracks, context, heads):
    additions = {}
    basis_current = bool(context and context["proposal"]["basisHeads"] == heads)
    for layer in sorted(_sound_layers(tracks), key=lambda value: value["order"]):
        choice = layer["provenance"]["soundSelection"]["choice"]
        additions.setdefault(choice["itemId"], {"selections": [], "opportunities": []})[
            "selections"
        ].append(_selection(layer))
    for record in (context or {}).get("proposal", {}).get("opportunities", []):
        additions.setdefault(record["itemId"], {"selections": [], "opportunities": []})[
            "opportunities"
        ].append(
            {
                "eventId": record["eventId"],
                "cueId": (record["opportunity"] or {}).get("cueId"),
                "purpose": record["intent"]["purpose"],
                "role": record["intent"]["role"],
                "recommendation": record["recommendation"]
                if basis_current
                else "unresolved",
                "proposedRecommendation": record["recommendation"],
                "silenceAllowed": record["silenceAllowed"],
                "issues": deepcopy(record["issues"]),
                "proposalRef": deepcopy(context["proposalRef"]),
                "basisCurrent": basis_current,
                "evidenceType": "proposed-metadata",
            }
        )
    for identity, addition in additions.items():
        if identity in items:
            items[identity]["sound"] = {
                "intent": deepcopy(items[identity].get("sound")),
                **addition,
            }
