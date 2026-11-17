"""Current and pending selected sound originals, without copying or decoding media."""

from .sound_choices import sound_source_id
from .sound_tracks import _sound_layers, validate_sound_tracks


def _source(entry, reference):
    return {
        "sourceId": sound_source_id(entry["entryId"], reference["sha256"]),
        "locator": reference["locator"],
        "fingerprint": {
            "sha256": reference["sha256"],
            "sizeBytes": entry["source"]["sizeBytes"],
        },
    }


def _current(workspace):
    store = workspace.store("tracks")
    if not store.path.exists() and not store.path.is_symlink():
        return []
    index = store.load_index()
    if index["headRevisionId"] is None:
        return []
    snapshot = store.revision(index["headRevisionId"])["snapshot"]
    validate_sound_tracks(snapshot)
    return [
        _source(
            layer["provenance"]["soundSelection"]["choice"]["sourceEntry"],
            layer["source"],
        )
        for layer in _sound_layers(snapshot)
    ]


def _pending(workspace):
    from .motion_retention import _Retention

    path = workspace.timeline_dir / "motion-application.pending.json"
    applications = workspace.raw_dir / "edit/motion/sound/applications"
    if not (
        path.exists()
        or path.is_symlink()
        or applications.exists()
        or applications.is_symlink()
    ):
        return []
    retained = _Retention(workspace)
    retained.sound_retention.load_applications()
    if path.exists() or path.is_symlink():
        marker, _ = retained.read(path)
        if set(marker) != {"operationId", "requestHash"}:
            raise ValueError("Invalid pending sound application marker")
        retained.sound_retention.pending(marker)
    return _future_sources(retained.sound_retention.applications.values())


def _future_sources(receipts):
    return [
        _source(choice["sourceEntry"], receipt["sourceRefs"][choice["eventId"]])
        for receipt in receipts
        if receipt["state"] != "committed"
        for choice in receipt["choices"]
        if choice["fit"]["status"] == "fit"
    ]


def reconstruction_sound_sources(workspace):
    """Describe required file identities; reconstruction still verifies physical bytes."""
    sources = _current(workspace) + _pending(workspace)
    unique = {}
    for source in sources:
        key = (source["sourceId"], source["locator"])
        if key in unique and unique[key] != source:
            raise ValueError(
                "Selected sound source identity has conflicting fingerprints"
            )
        unique[key] = source
    return list(unique.values())
