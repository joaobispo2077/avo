"""Optional ArtCraft command configuration and structured request input."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

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
    prepare = operations.add_parser(
        "prepare", help="Prepare one selected authoring job"
    )
    prepare.add_argument("--request-json", required=True)
    prepare.add_argument("--job-spec-json", required=True)
    for field in ("provider", "workspace", "app", "mode"):
        prepare.add_argument(f"--{field}", required=True)
    prepare.add_argument("--operation", action="append", required=True)
    prepare.add_argument("--cli")
    prepare.add_argument("--application")
    prepare.add_argument("--reuse-job")
    prepare.add_argument("--reuse-head")
    prepare.add_argument("--json", action="store_true")
    for operation, hint in (
        ("inspect", "Reconcile retained job evidence"),
        ("run", "Execute a prepared native job"),
        ("recover", "Inspect, retry or cancel a selected authoring job"),
    ):
        command = operations.add_parser(operation, help=hint)
        command.add_argument("--job", required=True)
        command.add_argument("--expected-head", required=True)
        if operation == "recover":
            command.add_argument(
                "--action", choices=("inspect", "retry", "cancel"), default="inspect"
            )
        command.add_argument("--json", action="store_true")
    register = operations.add_parser(
        "register", help="Register a verified ArtCraft export for one video"
    )
    for field in ("project", "job", "expected-head", "asset-id", "output"):
        register.add_argument(f"--{field}", required=True)
    register.add_argument("--json", action="store_true")
    review = operations.add_parser(
        "review", help="Inspect standalone and contextual ArtCraft review evidence"
    )
    review.add_argument("--job", required=True)
    review.add_argument("--expected-head", required=True)
    for field in ("project", "asset-id", "materialization"):
        review.add_argument(f"--{field}")
    review.add_argument("--json", action="store_true")
    interchange = operations.add_parser(
        "import-timeline", help="Validate the retained FilmCraft exchange"
    )
    for field in ("project", "job", "expected-head", "actor", "reason"):
        interchange.add_argument(f"--{field}", required=True)
    interchange.add_argument("--json", action="store_true")
    _provider_commands(operations)


def _provider_commands(operations):
    propose = operations.add_parser(
        "provider-propose", help="Propose a verified native provider package"
    )
    publish = operations.add_parser(
        "provider-publish", help="Publish a reviewed native provider package"
    )
    for command in (propose, publish):
        for field in ("provider", "catalog", "package", "source-root", "actor"):
            command.add_argument(f"--{field}", required=True)
        command.add_argument("--json", action="store_true")
    propose.add_argument("--pattern-json", required=True)
    propose.add_argument("--intent-reference", required=True)
    propose.add_argument(
        "--change-type", choices=("major", "minor", "patch"), default="major"
    )
    for field in ("proposal", "native-store", "expected-catalog", "reason"):
        publish.add_argument(f"--{field}", required=True)
    instantiate = operations.add_parser(
        "provider-instantiate", help="Pin an exact native package for a video"
    )
    for field in (
        "project",
        "catalog",
        "native-store",
        "kit-id",
        "version",
        "manifest-hash",
        "instance-id",
        "bindings-json",
    ):
        instantiate.add_argument(f"--{field}", required=True)
    instantiate.add_argument("--json", action="store_true")
    instantiate.add_argument("--supersedes", help="Explicitly upgrade a prior instance")


def _distinct_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate ArtCraft request field: {key}")
        result[key] = value
    return result


def _decode_object(raw):
    from avo.artcraft import ArtCraftError

    if len(raw.encode("utf-8")) > _MAX_REQUEST_BYTES:
        raise ArtCraftError("ArtCraft request exceeds 256 KiB")
    document = json.loads(raw, object_pairs_hook=_distinct_keys)
    if not isinstance(document, dict):
        raise ArtCraftError("ArtCraft request must be a structured object")
    return document


def _decode_request(raw):
    from avo.artcraft import validate_record

    return validate_record("request", _decode_object(raw))


def encode_request(value):
    """Serialize an actual tool argument, never interpret it as a client path."""
    return _encode_argument(value, "request", _decode_request)


def encode_job_spec(value):
    from avo.timeline.contracts import validate_document

    return _encode_argument(
        value,
        "job specification",
        lambda raw: validate_document(
            _decode_object(raw), "avo.artcraft.schema.json#/$defs/jobSpec"
        ),
    )


def _encode_argument(value, label, validate):
    from avo.artcraft import ArtCraftError
    from avo.timeline.contracts import canonical_json_bytes

    if not isinstance(value, Mapping):
        raise ArtCraftError(f"ArtCraft {label} must be a structured object")
    try:
        raw = canonical_json_bytes(dict(value)).decode("utf-8")
        validate(raw)
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


def _prepare_job(request, args):
    from avo.adapters.artcraft import SelectedArtCraftAdapter
    from avo.artcraft import (
        ArtCraftError,
        ArtCraftIntent,
        assess_request,
        prepare_authoring,
    )

    spec = _decode_object(args.job_spec_json)
    for key in ("provider", "workspace", "mode"):
        if spec.get(key) != getattr(args, key):
            raise ArtCraftError(
                f"ArtCraft job {key} differs from the selected invocation"
            )
    for key, selected in (("cliPath", args.cli), ("appPath", args.application)):
        if key in spec and spec[key] != selected:
            raise ArtCraftError(
                f"Select the exact installed ArtCraft {key} in the invocation"
            )
        if selected is not None:
            spec[key] = selected
    intent = ArtCraftIntent("explicit", args.app, tuple(args.operation))
    decision = assess_request(request, intent=intent)
    if any((args.reuse_job, args.reuse_head, args.mode == "reuse")):
        from avo.artcraft import prepare_authoring_reuse

        if not all((args.reuse_job, args.reuse_head)):
            raise ArtCraftError("Select both the retained job and its export head")
        return prepare_authoring_reuse(
            request,
            spec,
            from_job=args.reuse_job,
            from_head=args.reuse_head,
            intent=intent,
            decision=decision,
        )
    return prepare_authoring(
        request,
        spec,
        intent=intent,
        decision=decision,
        adapter=SelectedArtCraftAdapter(),
    )


def _review_export(args):
    from avo.artcraft import ArtCraftError, describe_export_review

    context = (args.project, args.asset_id, args.materialization)
    if any(context) and not all(context):
        raise ArtCraftError(
            "Contextual review requires the project, asset ID and proof materialization"
        )
    standalone = describe_export_review(args.job, expected_head=args.expected_head)
    if not args.project:
        return standalone

    from avo.proof_composition import review_artcraft_proof
    from avo.timeline.generated_assets import GeneratedAssetError
    from avo.timeline.proof_plan import ProofPlanError
    from avo.timeline.workspace import TimelineWorkspace, WorkspaceError

    try:
        return review_artcraft_proof(
            TimelineWorkspace.from_project(args.project),
            standalone,
            asset_id=args.asset_id,
            materialization_path=args.materialization,
        )
    except (GeneratedAssetError, ProofPlanError, WorkspaceError) as exc:
        raise ArtCraftError(str(exc), code="ARTCRAFT_REVIEW_UNAVAILABLE") from exc


def _provider_package_action(args):
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source
    from avo.artcraft import ArtCraftError
    from avo.timeline.animation import AnimationError
    from avo.timeline.contracts import ContractError
    from avo.timeline.provider_animation import ProviderAnimationService
    from avo.timeline.store import StoreError

    if args.artcraft_operation == "provider-instantiate":
        return _instantiate_native_provider(args, inspect_lower_third_source)
    catalog_path, package_path = Path(args.catalog), Path(args.package)
    if catalog_path.resolve() != catalog_path or package_path.resolve() != package_path:
        raise ArtCraftError("Choose exact absolute ArtCraft catalog and package paths")
    if package_path.stat().st_size > _MAX_REQUEST_BYTES:
        raise ArtCraftError("ArtCraft package manifest exceeds 256 KiB")
    package = _decode_object(package_path.read_text(encoding="utf-8"))
    service = ProviderAnimationService(catalog_path, provider=args.provider)
    options = {
        "package": package,
        "source_root": args.source_root,
        "source_observer": inspect_lower_third_source,
        "actor": args.actor,
    }
    try:
        if args.artcraft_operation == "provider-propose":
            return service.propose_native_package(
                _decode_object(args.pattern_json),
                intent_reference=args.intent_reference,
                change_type=args.change_type,
                **options,
            )
        return service.publish_native_package(
            args.proposal,
            native_store=args.native_store,
            reason=args.reason,
            expected_catalog_sha256=args.expected_catalog,
            **options,
        )
    except (AnimationError, ContractError, StoreError) as exc:
        raise ArtCraftError(str(exc), code="ARTCRAFT_PACKAGE_UNAVAILABLE") from exc


def _instantiate_native_provider(args, source_observer):
    from avo.artcraft import ArtCraftError
    from avo.timeline.component_instances import (
        ComponentInstanceError,
        ComponentInstanceService,
    )
    from avo.timeline.store import StoreError
    from avo.timeline.workspace import TimelineWorkspace, WorkspaceError

    bindings = _decode_object(args.bindings_json)
    if set(bindings) != {
        "parameters",
        "assetBindings",
        "eventBindings",
        "safeAreaBindings",
    }:
        raise ArtCraftError("Select parameters and the exact native instance bindings")
    try:
        service = ComponentInstanceService(TimelineWorkspace.from_project(args.project))
        return service.resolve_native_provider_kit(
            catalog_path=args.catalog,
            native_store=args.native_store,
            kit_id=args.kit_id,
            version=args.version,
            manifest_hash=args.manifest_hash,
            instance_id=args.instance_id,
            parameters=bindings["parameters"],
            asset_bindings=bindings["assetBindings"],
            event_bindings=bindings["eventBindings"],
            safe_area_bindings=bindings["safeAreaBindings"],
            source_observer=source_observer,
            supersedes_instance_id=args.supersedes,
        )
    except (ComponentInstanceError, StoreError, WorkspaceError) as exc:
        raise ArtCraftError(str(exc), code="ARTCRAFT_INSTANCE_UNAVAILABLE") from exc


def _register_export(args):
    from avo.artcraft import ArtCraftError
    from avo.proof_composition import register_artcraft_export
    from avo.timeline.generated_assets import GeneratedAssetError
    from avo.timeline.store import StoreError
    from avo.timeline.workspace import TimelineWorkspace, WorkspaceError

    try:
        return register_artcraft_export(
            TimelineWorkspace.from_project(args.project),
            job_ref=args.job,
            expected_head=args.expected_head,
            output=args.output,
            asset_id=args.asset_id,
        )
    except (GeneratedAssetError, StoreError, WorkspaceError) as exc:
        raise ArtCraftError(str(exc), code="ARTCRAFT_ADMISSION_REQUIRED") from exc


def _read_job(args):
    from avo.adapters.artcraft import SelectedArtCraftAdapter
    from avo.artcraft import inspect_authoring, recover_authoring

    if args.artcraft_operation == "recover":
        selected = SelectedArtCraftAdapter() if args.action == "retry" else None
        return recover_authoring(
            args.job,
            expected_head=args.expected_head,
            action=args.action,
            adapter=selected,
        )
    return inspect_authoring(
        args.job,
        expected_head=args.expected_head,
        source_inspector=SelectedArtCraftAdapter.inspect_returned_source,
    )


def _import_timeline(args):
    from avo.artcraft import read_authoring_export
    from avo.timeline_import_cli import create_service

    job, event = read_authoring_export(args.job, expected_head=args.expected_head)
    return create_service(args).prepare_filmcraft_return(
        job, event, actor=args.actor, reason=args.reason
    )


def run(args):
    from avo.artcraft import ArtCraftError, assess_request, catalog

    try:
        if args.artcraft_operation == "catalog":
            result = catalog(app=args.app, behavior=args.behavior)
        elif args.artcraft_operation == "prepare":
            result = _prepare_job(_decode_request(args.request_json), args)
        elif args.artcraft_operation in {"inspect", "recover"}:
            result = _read_job(args)
        elif args.artcraft_operation == "run":
            from avo.adapters.artcraft import SelectedArtCraftAdapter
            from avo.artcraft import run_authoring

            result = run_authoring(
                args.job,
                expected_head=args.expected_head,
                adapter=SelectedArtCraftAdapter(),
            )
        elif args.artcraft_operation == "register":
            result = _register_export(args)
        elif args.artcraft_operation in {"review", "import-timeline"}:
            handlers = {"review": _review_export, "import-timeline": _import_timeline}
            result = handlers[args.artcraft_operation](args)
        elif args.artcraft_operation in {
            "provider-propose",
            "provider-publish",
            "provider-instantiate",
        }:
            result = _provider_package_action(args)
        else:
            request = _decode_request(args.request_json)
            result = assess_request(
                request, intent=_assessment_intent(args), routes=_native_routes(request)
            )
    except ArtCraftError:
        raise
    except (ValueError, OSError) as exc:
        raise ArtCraftError(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
