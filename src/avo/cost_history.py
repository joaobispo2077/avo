"""History from declared local locators and portable provider exports."""

import re
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath

from avo import avo_state
from avo.cost_store import CostError, CostStore, content_hash, read_json
from avo.costs import summarize
from avo.paths import providers_dir


def remember(store):
    root = avo_state.state_dir() / "cost-locators"
    identity = store.identity()
    if identity:
        locator = {
            "rawDir": str(store.raw_dir),
            "accountingVideoId": identity["accountingVideoId"],
            "archive": store.root == store.raw_dir,
        }
        CostStore(root, archive=True).publish(f"{content_hash(locator)}.json", locator)


def assert_binding_available(store, source, session, boundary):
    from avo.cost_sources import _active_bindings

    sources = [store]
    for path in (avo_state.state_dir() / "cost-locators").glob("*.json"):
        try:
            locator = read_json(path)
            sources.append(
                CostStore(locator["rawDir"], archive=locator.get("archive", False))
            )
        except (OSError, ValueError, KeyError):
            continue
    bindings = {
        b["bindingId"]: b
        for candidate in sources
        for b in _active_bindings(candidate, None)
        if Path(b["source"]).resolve() == Path(source).resolve()
        and b["sourceSessionId"] == session
    }
    _assert_disjoint(list(bindings.values()), boundary)


def _assert_disjoint(bindings, boundary):
    if not bindings:
        return
    if any(not b.get("endBoundary") for b in bindings):
        raise CostError(
            "source session already bound; close its interval before reusing it"
        )
    intervals = {b["boundary"]: b["endBoundary"] for b in bindings}
    starts = set(intervals) - set(intervals.values())
    if len(intervals) != len(bindings) or len(starts) != 1:
        raise CostError("source session binding intervals are ambiguous")
    cursor = _interval_end(intervals, starts.pop())
    if cursor != boundary:
        raise CostError(
            "new source binding must start at the prior recorded end boundary"
        )


def _interval_end(intervals, cursor):
    visited = set()
    while cursor in intervals and cursor not in visited:
        visited.add(cursor)
        cursor = intervals[cursor]
    if len(visited) != len(intervals):
        raise CostError("source session binding intervals are ambiguous")
    return cursor


def _history_sources(store):
    sources = [store] if store else []
    for path in (avo_state.state_dir() / "cost-locators").glob("*.json"):
        try:
            locator = read_json(path)
            sources.append(
                CostStore(locator["rawDir"], archive=locator.get("archive", False))
            )
        except (OSError, ValueError, KeyError):
            continue
    for path in providers_dir().glob("*/learndowns/*/costs/identity.json"):
        sources.append(CostStore(path.parent, archive=True))
    return sources


def _source_report(source, provider, video_id):
    identity = source.identity()
    if (
        not identity
        or (provider and identity["provider"] != provider)
        or (video_id and identity["videoId"] != video_id)
    ):
        return None
    snapshots = source.documents("snapshots")
    closed = [s for s in snapshots if s.get("lifecycle") in {"final", "amendment"}]
    report = max(closed, key=_snapshot_order) if closed else summarize(source)
    return identity["accountingVideoId"], report


def _history_preference(report, previous, projected, previous_projected):
    from avo.cost_store import _membership_entries

    current = _membership_entries(report.get("membership", {}))
    earlier = _membership_entries(previous.get("membership", {}))
    if current > earlier:
        return True
    if earlier > current or current != earlier:
        return False
    if projected != previous_projected:
        return not projected
    return _snapshot_order(report) > _snapshot_order(previous)


def _history_capture_conflict(report, previous):
    from avo.cost_store import _membership_entries

    current = _membership_entries(report.get("membership", {}))
    earlier = _membership_entries(previous.get("membership", {}))
    return not current.issubset(earlier) and not earlier.issubset(current)


def _consider_history_report(videos, projections, diagnostics, key, report, status):
    if key in videos and _history_capture_conflict(report, videos[key]):
        diagnostics.append(
            {"code": "history-capture-conflict", "accountingVideoId": key}
        )
    if key not in videos or _history_preference(
        report, videos[key], status is not None, key in projections
    ):
        videos[key] = report
        if status:
            projections[key] = {"accountingVideoId": key, **status}
        else:
            projections.pop(key, None)


def history(*, provider=None, video_id=None, store=None):
    videos = {}
    diagnostics = []
    for source in _history_sources(store):
        try:
            selected = _source_report(source, provider, video_id)
            if selected is None:
                continue
            key, report = selected
            # Prefer explicit snapshot chronology; never sum copies of a video.
            if key not in videos or _snapshot_order(report) > _snapshot_order(
                videos[key]
            ):
                videos[key] = report
        except (OSError, CostError, KeyError, TypeError):
            diagnostics.append({"code": "history-source-unavailable"})
    videos.update(_legacy_reports(provider, video_id))
    return {
        "schemaVersion": "1.0.0",
        "status": "ok",
        "videos": list(videos.values()),
        "diagnostics": diagnostics,
        "message": ""
        if videos
        else "No recorded video costs. Run a pipeline with an explicitly bound usage source.",
    }


def _legacy_reports(provider, video_id):
    result = {}
    for path in providers_dir().glob("*/learndowns/*/learndown.json"):
        try:
            value = read_json(path)
            if (path.parent / "costs/identity.json").is_file() or (
                value.get("costs") or {}
            ).get("accountingVideoId"):
                continue
            report = _legacy_report(value)
            if provider and report["provider"] != provider:
                continue
            if video_id and report["videoId"] != video_id:
                continue
            result[content_hash({"entry": str(path)})] = report
        except (OSError, ValueError, TypeError):
            continue
    return result


def _legacy_report(value):
    return {
        "schemaVersion": "1.0.0",
        "status": "ok",
        "accountingVideoId": None,
        "provider": value.get("provider"),
        "videoId": value.get("entryId"),
        "lifecycle": value.get("status", "draft"),
        "coverage": "not-recorded",
        "cutoff": None,
        "tokens": {"total": None},
        "amounts": [],
        "observationCount": 0,
        "diagnostics": [{"code": "legacy-costs-not-recorded"}],
    }


def _snapshot_order(value):
    return (value.get("recordedOrder", 0), value.get("snapshotId") or "")


def trends(report):
    cohorts = {}
    for video in report["videos"]:
        if video.get("lifecycle") not in {"final", "amendment"}:
            continue
        for amount in video["amounts"]:
            key = (
                amount["basis"],
                amount["unit"],
                video["coverage"],
                tuple(sorted(video.get("breakdowns", {}).get("serviceClass", {}))),
                tuple(sorted(video.get("excludedCosts", []))),
            )
            cohorts.setdefault(key, []).append(amount["amount"])
    from decimal import Decimal

    return [
        {
            "basis": b,
            "unit": u,
            "coverage": c,
            "serviceClasses": list(scope),
            "excludedCosts": list(exclusions),
            "sampleSize": len(values),
            "meanPerVideo": str(sum(map(Decimal, values)) / len(values))
            if len(values) >= 2
            else None,
            "inclusion": "recorded completed videos with matching basis, unit, coverage, service classes and exclusions; no duration normalization",
            "limitations": "Partial coverage is not a complete production-cost comparison; no savings prediction",
        }
        for (b, u, c, scope, exclusions), values in sorted(cohorts.items())
    ]


_PORTABLE_LIMITS = [
    "omitted-preimages-not-verifiable",
    "source-reauthorization-required",
]
_PORTABLE_OMISSIONS = {
    "local-source-locator",
    "collection-grant",
    "unrecognized-fields",
    "local-receipt-locator",
}
_PORTABLE_SCHEMAS = {
    "identity": "identity",
    "batches": "batch",
    "bindings": "binding",
    "prices": "price",
    "corrections": "correction",
    "snapshots": "snapshot",
    "profiles": "profile",
    "participations": "participation",
    "estimates": "estimate",
    "reconciliations": "reconciliation",
}
_PORTABLE_IDS = {
    "identity": "accountingVideoId",
    "batches": "batchId",
    "bindings": "bindingId",
    "corrections": "correctionId",
    "snapshots": "snapshotId",
    "profiles": "profileId",
    "participations": "factId",
    "estimates": "estimateId",
    "reconciliations": "reconciliationId",
}
_PORTABLE_RECORD_FIELDS = {
    "kind",
    "id",
    "path",
    "originalDigest",
    "projectedDigest",
    "originalMembershipDigest",
    "omissions",
}
_PORTABLE_MANIFEST_FIELDS = {
    "schemaVersion",
    "accountingVideoId",
    "manifestId",
    "predecessorManifestId",
    "verification",
    "sourceReauthorizationRequired",
    "limitations",
    "records",
}


def _portable_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _portable_record_path(record):
    path = _portable_relative_json(record["path"])
    kind = record["kind"]
    expected = "projections/bindings/" if kind == "bindings" else kind + "/"
    if kind == "identity":
        if path != "identity.json":
            raise CostError("invalid portable identity path")
    elif not path.startswith(expected):
        raise CostError("invalid portable record family path")
    return path


def _portable_relative_json(path):
    if not isinstance(path, str) or "\\" in path or ":" in path:
        raise CostError("invalid portable metadata path")
    parts = PurePosixPath(path)
    if parts.is_absolute() or ".." in parts.parts or not path.endswith(".json"):
        raise CostError("invalid portable metadata path")
    return path


def _portable_validate_record(record):
    if not isinstance(record, dict) or set(record) != _PORTABLE_RECORD_FIELDS:
        raise CostError("invalid portable projection record")
    if not isinstance(record["kind"], str) or record["kind"] not in _PORTABLE_SCHEMAS:
        raise CostError("invalid portable projection family")
    if not isinstance(record["id"], str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,500}", record["id"]
    ):
        raise CostError("invalid portable record identity")
    _portable_record_digests(record)
    _portable_validate_omissions(record["omissions"])
    _portable_record_path(record)


def _portable_validate_omissions(omissions):
    if not isinstance(omissions, list) or not all(
        isinstance(v, str) and v in _PORTABLE_OMISSIONS for v in omissions
    ):
        raise CostError("invalid portable omission declaration")


def _portable_record_digests(record):
    if not all(
        _portable_hash(record[field])
        for field in ("originalDigest", "projectedDigest", "originalMembershipDigest")
    ):
        raise CostError("invalid portable projection digest")
    if (
        not record["omissions"]
        and record["originalDigest"] != record["projectedDigest"]
    ):
        raise CostError("portable omitted preimage lacks an explicit limitation")


def _portable_validate_manifest(value):
    if not isinstance(value, dict) or set(value) != _PORTABLE_MANIFEST_FIELDS:
        raise CostError("invalid portable metadata manifest")
    expected = ("2.0.0", "metadata-projection", True, _PORTABLE_LIMITS)
    actual = (
        value["schemaVersion"],
        value["verification"],
        value["sourceReauthorizationRequired"],
        value["limitations"],
    )
    if actual != expected or type(value["sourceReauthorizationRequired"]) is not bool:
        raise CostError("invalid portable verification contract")
    predecessor = value["predecessorManifestId"]
    if predecessor is not None and not _portable_hash(predecessor):
        raise CostError("invalid portable predecessor manifest")
    _portable_manifest_hash(value)
    _portable_validate_records(value["records"])
    return value


def _portable_manifest_hash(value):
    expected = content_hash({k: v for k, v in value.items() if k != "manifestId"})
    if not _portable_hash(value["manifestId"]) or value["manifestId"] != expected:
        raise CostError("portable manifest integrity verification failed")


def _portable_validate_records(records):
    if not isinstance(records, list) or not records or len(records) > 100000:
        raise CostError("invalid portable record membership")
    identities, paths = set(), set()
    for record in records:
        _portable_validate_record(record)
        identity = (record["kind"], record["id"])
        if identity in identities or record["path"] in paths:
            raise CostError("duplicate portable projection membership")
        identities.add(identity)
        paths.add(record["path"])


def _portable_extension(previous, current):
    if previous["accountingVideoId"] != current["accountingVideoId"]:
        raise CostError("portable destination belongs to another production")
    records = {(r["kind"], r["id"]): r for r in current["records"]}
    for record in previous["records"]:
        if records.get((record["kind"], record["id"])) != record:
            raise CostError(
                "portable export cannot remove or change a prior immutable projection"
            )


def _portable_manifest(store):
    from avo.cost_store import validate

    pointer = store.path("portable.json")
    if not pointer.is_file():
        return None
    value = _portable_validate_manifest(read_json(pointer))
    immutable = read_json(store.path(f"portable-manifests/{value['manifestId']}.json"))
    if immutable != value:
        raise CostError("portable manifest index integrity verification failed")
    identity = validate("identity", read_json(store.path("identity.json")))
    _portable_verify_identity(value, identity)
    if any(store.path("bindings").glob("*.json")):
        raise CostError("portable metadata cannot contain local collection grants")
    _portable_manifest_ancestors(store, value)
    return value


def _portable_manifest_ancestors(store, manifest):
    ancestors, seen = [], {manifest["manifestId"]}
    current = manifest
    while current["predecessorManifestId"]:
        identifier = current["predecessorManifestId"]
        if identifier in seen:
            raise CostError("portable manifest ancestry contains a cycle")
        parent = _portable_validate_manifest(
            read_json(store.path(f"portable-manifests/{identifier}.json"))
        )
        if parent["manifestId"] != identifier:
            raise CostError("portable ancestor manifest integrity verification failed")
        _portable_extension(parent, current)
        ancestors.append(parent)
        seen.add(identifier)
        current = parent
    return ancestors


def _portable_verify_identity(manifest, identity):
    records = [r for r in manifest["records"] if r["kind"] == "identity"]
    if (
        len(records) != 1
        or manifest["accountingVideoId"] != identity["accountingVideoId"]
    ):
        raise CostError("portable projection identity mismatch")
    if records[0]["projectedDigest"] != content_hash(identity):
        raise CostError("portable identity integrity verification failed")


def _portable_validate_payload(kind, value, identity):
    from avo.cost_store import (
        RECORD_TYPES,
        _record_owner,
        _verify_batch,
        _verify_record,
        validate,
    )

    if kind == "bindings":
        if "source" in value:
            raise CostError("portable binding metadata cannot grant collection")
        validate("binding", {**value, "source": "omitted-portable-source"})
    else:
        validate(_PORTABLE_SCHEMAS[kind], value)
    if kind == "batches":
        _verify_batch(value, identity)
    elif kind in RECORD_TYPES:
        _verify_record(kind, value)
        _record_owner(value, identity)


def _portable_load_record(store, record, identity):
    value = read_json(store.path(_portable_record_path(record)))
    if content_hash(value) != record["projectedDigest"]:
        raise CostError("portable projection integrity verification failed")
    _portable_validate_payload(record["kind"], value, identity)
    return value


def _portable_documents(store, kind, manifest):
    identity = store.identity()
    return [
        _portable_load_record(store, r, identity)
        for r in manifest["records"]
        if r["kind"] == kind
    ]


def _portable_read_snapshot(store, snapshot_id, manifest):
    snapshots = [r for r in manifest["records"] if r["kind"] == "snapshots"]
    original = [r for r in snapshots if r["id"] == snapshot_id]
    if original and original[0]["omissions"]:
        raise CostError(
            "original snapshot preimage omitted from portable projection; inspect its derived snapshot identity"
        )
    matches = [r for r in snapshots if PurePosixPath(r["path"]).stem == snapshot_id]
    if len(matches) != 1:
        raise CostError("cost snapshot unavailable in portable projection")
    return _portable_load_record(store, matches[0], store.identity())


def _portable_membership(store, kind, value):
    manifest = _portable_manifest(store)
    if manifest is None:
        return None
    digest = content_hash(value)
    records = [
        r
        for r in manifest["records"]
        if r["kind"] == kind and r["projectedDigest"] == digest
    ]
    if len(records) != 1:
        raise CostError("portable record is outside captured projection membership")
    return records[0]["originalMembershipDigest"]


def _portable_sanitize(value, schema):
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        pairs = [_portable_sanitize(item, schema["items"]) for item in value]
        return [v for v, _ in pairs], any(removed for _, removed in pairs)
    if not isinstance(value, dict) or "properties" not in schema:
        return deepcopy(value), False
    properties = schema["properties"]
    result, removed = {}, bool(set(value) - set(properties))
    for key in set(value) & set(properties):
        result[key], nested = _portable_sanitize(value[key], properties[key])
        removed = removed or nested
    return result, removed


def _portable_legacy_batch(value):
    from avo.paths import schema_path

    schema = read_json(schema_path("avo.cost-batch.schema.json"))
    projected, removed = _portable_sanitize(value, schema)
    categories = set(
        schema["properties"]["observations"]["items"]["properties"]["tokens"][
            "properties"
        ]
    )
    for row in projected["observations"]:
        semantics = row["semantics"]
        removed = removed or bool(set(semantics) - categories)
        row["semantics"] = {k: v for k, v in semantics.items() if k in categories}
    if removed:
        projected["observationKeys"] = deepcopy(
            value.get("observationKeys", CostStore.keys_for(value["observations"]))
        )
        projected["contentHash"] = content_hash(
            {k: v for k, v in projected.items() if k != "contentHash"}
        )
    return projected, ["unrecognized-fields"] if removed else []


def _portable_local_locator(value):
    if not isinstance(value, str):
        return False
    return bool(
        PureWindowsPath(value).drive
        or PurePosixPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or value.startswith("file:")
    )


def _portable_snapshot(value):
    closure = value.get("closureEvidence") or {}
    if not _portable_local_locator(closure.get("receiptPath")):
        return deepcopy(value), []
    projected = deepcopy(value)
    projected["closureEvidence"]["receiptPath"] = "omitted-local-receipt"
    projected["snapshotId"] = content_hash(
        {k: v for k, v in projected.items() if k not in {"snapshotId", "recordedOrder"}}
    )
    return projected, ["local-receipt-locator"]


def _portable_project(kind, value, identity):
    from avo.cost_store import _verify_batch, validate

    omissions = []
    if kind == "bindings":
        projected = {k: deepcopy(v) for k, v in value.items() if k != "source"}
        omissions = ["local-source-locator", "collection-grant"]
    elif kind == "snapshots":
        projected, omissions = _portable_snapshot(value)
    elif kind == "batches" and value.get("schemaVersion", "1.0.0") == "1.0.0":
        _verify_batch(value, identity)
        projected, omissions = _portable_legacy_batch(value)
    else:
        validate(_PORTABLE_SCHEMAS[kind], value)
        projected = deepcopy(value)
    _portable_validate_payload(kind, projected, identity)
    return projected, omissions


def _portable_prepare_record(store, kind, value):
    projected, omissions = _portable_project(kind, value, store.identity())
    identity = value.get(_PORTABLE_IDS.get(kind), content_hash(value))
    file_id = projected.get("snapshotId") if kind == "snapshots" else identity
    path = f"{kind}/{file_id}.json"
    if kind == "identity":
        path = "identity.json"
    elif kind == "bindings":
        path = f"projections/bindings/{identity}.json"
    record = {
        "kind": kind,
        "id": identity,
        "path": path,
        "originalDigest": content_hash(value),
        "projectedDigest": content_hash(projected),
        "originalMembershipDigest": store.membership_digest(kind, value),
        "omissions": omissions,
    }
    _portable_validate_record(record)
    return record, projected


def _portable_prepare(store):
    view = store.capture()
    records = [_portable_prepare_record(store, "identity", store.identity())]
    for kind, values in {**view, "snapshots": store.documents("snapshots")}.items():
        records.extend(_portable_prepare_record(store, kind, value) for value in values)
    return sorted(records, key=lambda item: (item[0]["kind"], item[0]["id"]))


def _portable_export_destination(store, destination):
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(store.root) or store.root.is_relative_to(destination):
        raise CostError("portable export destination overlaps canonical source storage")
    return CostStore(destination, archive=True)


def _portable_export_publish(target, relative, value, *, replace=False):
    from avo.cost_store import _directory_lock

    path = target.path(relative)
    with _directory_lock(path.with_suffix(".lock")):
        if path.is_file() and read_json(path) == value:
            return
        if path.exists() and not replace:
            raise CostError(
                "immutable portable export conflicts with existing metadata"
            )
        target._publish_locked(path, value)


def _portable_target_files(target, prepared, previous):
    expected = {r["path"]: value for r, value in prepared}
    expected["format.json"] = {"schemaVersion": "2.0.0", "minimumReader": "2.0.0"}
    for path in target.root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(target.root).as_posix()
        if previous and relative == "portable.json":
            continue
        if previous and relative.startswith("portable-manifests/"):
            _portable_target_manifest(relative, path)
            continue
        if relative not in expected or read_json(path) != expected[relative]:
            raise CostError(
                "portable export needs a clean destination; existing unmanaged metadata requires review"
            )


def _portable_target_manifest(relative, path):
    manifest = _portable_validate_manifest(read_json(path))
    if relative != f"portable-manifests/{manifest['manifestId']}.json":
        raise CostError("portable destination contains unmanaged manifest metadata")


def _portable_build_manifest(store, prepared, previous):
    records = [r for r, _ in prepared]
    if previous and previous["records"] == records:
        return previous
    manifest = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "verification": "metadata-projection",
        "sourceReauthorizationRequired": True,
        "limitations": list(_PORTABLE_LIMITS),
        "records": records,
        "predecessorManifestId": previous["manifestId"] if previous else None,
    }
    manifest["manifestId"] = content_hash(manifest)
    _portable_validate_manifest(manifest)
    if previous:
        _portable_extension(previous, manifest)
    return manifest


def _portable_write_projection(store, target, prepared):
    from avo.cost_store import _directory_lock

    with _directory_lock(target.path("portable-export.lock")):
        previous = _portable_manifest(target)
        manifest = _portable_build_manifest(store, prepared, previous)
        _portable_target_files(target, prepared, previous)
        for record, value in prepared:
            _portable_export_publish(target, record["path"], value)
        _portable_export_publish(
            target, "format.json", {"schemaVersion": "2.0.0", "minimumReader": "2.0.0"}
        )
        _portable_export_publish(
            target, f"portable-manifests/{manifest['manifestId']}.json", manifest
        )
        _portable_export_publish(target, "portable.json", manifest, replace=True)


def _portable_copy_projection(store, target, manifest):
    from avo.cost_store import _directory_lock

    prepared = [
        (r, _portable_load_record(store, r, store.identity()))
        for r in manifest["records"]
    ]
    ancestors = _portable_manifest_ancestors(store, manifest)
    with _directory_lock(target.path("portable-export.lock")):
        previous = _portable_manifest(target)
        if previous:
            _portable_extension(previous, manifest)
        _portable_target_files(target, prepared, previous)
        for record, value in prepared:
            _portable_export_publish(target, record["path"], value)
        _portable_export_publish(
            target, "format.json", {"schemaVersion": "2.0.0", "minimumReader": "2.0.0"}
        )
        for ancestor in [*ancestors, manifest]:
            _portable_export_publish(
                target, f"portable-manifests/{ancestor['manifestId']}.json", ancestor
            )
        _portable_export_publish(target, "portable.json", manifest, replace=True)


def _portable_export(store, destination):
    target = _portable_export_destination(store, destination)
    if not store.identity():
        return
    manifest = _portable_manifest(store)
    if manifest:
        return _portable_copy_projection(store, target, manifest)
    prepared = _portable_prepare(store)
    if (
        any(record["omissions"] for record, _ in prepared)
        or target.path("portable.json").exists()
    ):
        return _portable_write_projection(store, target, prepared)
    if any(target.path("bindings").glob("*.json")):
        raise CostError(
            "portable export needs a clean destination without local grants"
        )
    for record, value in prepared:
        target.publish(record["path"], value)
    if store.path("format.json").is_file():
        target._enable_v2()
