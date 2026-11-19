"""Optional ArtCraft command configuration and structured request input."""

from __future__ import annotations

import json
from collections.abc import Mapping

_MAX_REQUEST_BYTES = 256 * 1024


def configure(sub):
    parser = sub.add_parser("artcraft", help="Optional ArtCraft component authoring")
    operations = parser.add_subparsers(dest="artcraft_operation", required=True)
    assess = operations.add_parser("assess", help="Assess one authoring request")
    assess.add_argument("--request-json", required=True)
    assess.add_argument("--app")
    assess.add_argument("--operation", action="append", default=[])
    assess.add_argument("--knowledge-only", action="store_true")
    assess.add_argument("--json", action="store_true")
    index = operations.add_parser("catalog", help="Read bundled capability notes")
    index.add_argument("--app")
    index.add_argument("--behavior")
    index.add_argument("--json", action="store_true")


def _distinct_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate ArtCraft request field: {key}")
        result[key] = value
    return result


def _decode_request(raw):
    from avo.artcraft import ArtCraftError, validate_record

    if len(raw.encode("utf-8")) > _MAX_REQUEST_BYTES:
        raise ArtCraftError("ArtCraft request exceeds 256 KiB")
    return validate_record("request", json.loads(raw, object_pairs_hook=_distinct_keys))


def encode_request(value):
    """Serialize an actual tool argument, never interpret it as a client path."""
    from avo.artcraft import ArtCraftError
    from avo.timeline.contracts import canonical_json_bytes

    if not isinstance(value, Mapping):
        raise ArtCraftError("ArtCraft request must be a structured object")
    try:
        raw = canonical_json_bytes(dict(value)).decode("utf-8")
        _decode_request(raw)
    except ValueError as exc:
        raise ArtCraftError(str(exc)) from exc
    return raw


def _assessment_intent(args):
    from avo.artcraft import ArtCraftError, ArtCraftIntent

    if args.knowledge_only:
        if args.operation:
            raise ArtCraftError(
                "Knowledge assessment cannot select authoring operations"
            )
        return ArtCraftIntent("knowledge", args.app)
    if args.app and args.operation:
        return ArtCraftIntent("explicit", args.app, tuple(args.operation))
    if args.app or args.operation:
        raise ArtCraftError("Select the app and at least one operation together")
    return ArtCraftIntent()


def _native_routes(request):
    from avo.artcraft import CurrentArtCraftRoutes
    from avo.capabilities import default_proof_capability_registry
    from avo.timeline.contracts import content_hash

    requirement = request["required"]
    behavior = requirement["behavior"]
    native_roles = {
        "camera-transform-v1": "generated-clip",
        "opacity-fade": "generated-clip",
        "overlay-image": "generated-clip",
        "overlay-video": "generated-clip",
        "gain": "generated-audio",
    }
    if (
        requirement["editable"]
        or native_roles.get(behavior) != requirement["outputRole"]
    ):
        return None
    resolved = default_proof_capability_registry().resolve(behavior)
    if resolved is None:
        return None
    return CurrentArtCraftRoutes(
        request["provider"],
        request["componentId"],
        content_hash(requirement),
        (
            {
                "route": resolved.implementation_id,
                "contractRef": f"avo:proof:{resolved.capability}@{resolved.version}",
                "contractHash": resolved.sha256,
                "status": "sufficient",
                "reason": "Current built-in proof contract implements the required operation.",
            },
        ),
    )


def run(args):
    from avo.artcraft import ArtCraftError, assess_request, catalog

    try:
        if args.artcraft_operation == "catalog":
            result = catalog(app=args.app, behavior=args.behavior)
        else:
            request = _decode_request(args.request_json)
            result = assess_request(
                request, intent=_assessment_intent(args), routes=_native_routes(request)
            )
    except ValueError as exc:
        raise ArtCraftError(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
