"""History from declared local locators and portable provider exports."""

from pathlib import Path

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
