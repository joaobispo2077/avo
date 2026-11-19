"""Shared data-only catalogue identities and validation; no source execution."""

from __future__ import annotations

import re

from avo.timeline.contracts import content_hash

LIBRARY_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024


class SfxCatalogError(ValueError):
    """A catalogue request cannot safely complete against its recorded basis."""


def _hash(value, excluded):
    return content_hash({key: item for key, item in value.items() if key != excluded})


def _entry_id(library, relative):
    return content_hash({"libraryId": library, "relativePath": relative})


def _validate_facts(facts):
    count, total = facts["analyzedSamples"], facts["sourceSamples"]
    useful = facts["usefulRange"]
    if not 0 <= useful["startSample"] <= useful["endSampleExclusive"] <= count:
        raise SfxCatalogError("measured useful range exceeds actually analyzed samples")
    if total is not None and total < count:
        raise SfxCatalogError("analyzed samples exceed source length")
    if facts["coverage"] == "complete" and total != count:
        raise SfxCatalogError(
            "complete analysis requires exact observed source coverage"
        )
    _validate_amplitudes(facts)
    for field in ("onsets", "energyPeaks"):
        if any(sample >= count for sample in facts[field]):
            raise SfxCatalogError("measured marker lies outside analyzed source range")


def _validate_amplitudes(facts):
    if facts["rms"] > facts["peak"] + 1e-12:
        raise SfxCatalogError("measured RMS exceeds measured peak")
    centroid = facts["spectralCentroidHz"]
    if centroid is not None and centroid > facts["sampleRate"] / 2:
        raise SfxCatalogError("measured spectral centroid exceeds native Nyquist rate")


def _validate_entries(entries):
    seen = set()
    for entry in entries:
        _validate_entry_path(entry)
        if entry["entryId"] in seen or entry["entryId"] != _entry_id(
            entry["libraryId"], entry["relativePath"]
        ):
            raise SfxCatalogError("duplicate or mismatched catalogue entry identity")
        seen.add(entry["entryId"])
        facts = entry["measurement"]
        if facts:
            _validate_facts(facts)
            if (
                facts["measurementHash"] != _hash(facts, "measurementHash")
                or facts["sourceSha256"] != entry["source"]["sha256"]
            ):
                raise SfxCatalogError("measurement/source hash identity mismatch")
        if entry["entryRevision"] != _revision(entry):
            raise SfxCatalogError("catalogue entry revision identity mismatch")


def _validate_entry_path(entry):
    relative = entry["relativePath"]
    if (
        not LIBRARY_ID.fullmatch(entry["libraryId"])
        or relative.startswith("/")
        or "\\" in relative
        or ":" in relative
        or ".." in relative.split("/")
    ):
        raise SfxCatalogError("invalid catalogue source locator")


def _revision(entry):
    return content_hash(
        {
            "entryId": entry["entryId"],
            "sourceSha256": entry["source"]["sha256"],
            "measurementHash": (entry["measurement"] or {}).get("measurementHash"),
        }
    )
