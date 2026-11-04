"""Profile admission never implies unverified host/version support."""

from copy import deepcopy

import pytest

from avo.cost_profiles import (
    profile_id,
    profile_status,
    resolve_profile,
    validate_profile,
)
from avo.cost_store import CostError


def profile(**changes):
    value = {
        "schemaVersion": "2.0.0",
        "agent": "synthetic-agent",
        "surface": "test-runtime",
        "versions": ["fixture-1"],
        "sourceFormat": "test-projection",
        "parserVersion": "fixture-1",
        "parserDigest": "a" * 64,
        "fixtureDigests": ["b" * 64],
        "references": [
            {"url": "https://example.invalid/contract", "date": "2026-10-31"}
        ],
        "capability": "qualified",
        "semantics": {
            "counter": "request",
            "categoryOverlap": {"cacheRead": "input", "reasoning": "output"},
            "aggregateScope": "request",
            "revision": "explicit-final",
            "resume": "new-activities",
            "fork": "baseline-required",
            "reset": "epoch-required",
            "finality": "source-flush",
        },
        "identityFields": ["session_id", "request_id"],
        "allowedFields": ["session_id", "request_id", "tokens"],
        "limitations": ["Synthetic projection, not native product support."],
        "qualification": {"kind": "synthetic", "evidenceRefs": ["c" * 64]},
    }
    value.update(changes)
    value["profileId"] = profile_id(value)
    return value


def query(**changes):
    return {
        "agent": "synthetic-agent",
        "surface": "test-runtime",
        "version": "fixture-1",
        "source_format": "test-projection",
        **changes,
    }


def test_frozen_profile_identity_covers_semantics_and_rejects_tampering():
    value = profile()
    assert validate_profile(value) == value
    reordered = dict(reversed(list(value.items())))
    assert profile_id(reordered) == value["profileId"]
    changed = deepcopy(value)
    changed["semantics"]["counter"] = "cumulative"
    assert profile_id(changed) != value["profileId"]
    with pytest.raises(CostError, match="integrity"):
        validate_profile(changed)


def test_synthetic_qualification_requires_explicit_opt_in():
    value = profile()
    assert profile_status(value, version="fixture-1") == "candidate"
    assert resolve_profile([value], **query()) is None
    assert resolve_profile([value], **query(), allow_synthetic=True) == value


def test_admitted_native_profile_matches_without_exposing_mutable_registry_state():
    value = profile(qualification={"kind": "native", "evidenceRefs": ["c" * 64]})
    assert profile_status(value, version="fixture-1") == "qualified"
    selected = resolve_profile([value], **query())
    selected["semantics"]["counter"] = "unknown"
    assert value["semantics"]["counter"] == "request"


def test_qualified_profile_requires_admission_evidence():
    with pytest.raises(CostError):
        validate_profile(profile(qualification={"kind": "native", "evidenceRefs": []}))


@pytest.mark.parametrize(
    "changes",
    [
        {"version": None},
        {"version": "fixture-2"},
        {"agent": "another-agent"},
        {"surface": "desktop"},
        {"source_format": "another-source"},
    ],
)
def test_qualified_profile_never_matches_another_scope_or_unknown_version(changes):
    assert (
        resolve_profile([profile()], **query(**changes), allow_synthetic=True) is None
    )


@pytest.mark.parametrize("capability", ["candidate", "manual-only", "unavailable"])
def test_documented_or_fallback_profile_is_never_promoted(capability):
    value = profile(capability=capability, versions=[])
    assert (
        profile_status(value, version="fixture-1", allow_synthetic=True) == capability
    )
    assert resolve_profile([value], **query(), allow_synthetic=True) is None


def test_conflicting_qualified_profiles_require_an_explicit_choice():
    first = profile()
    second = profile(parserVersion="fixture-2")
    with pytest.raises(CostError, match="ambiguous"):
        resolve_profile([first, second], **query(), allow_synthetic=True)
    assert resolve_profile([first, first], **query(), allow_synthetic=True) == first


def test_rejected_private_fields_do_not_echo_their_contents():
    value = profile(prompt="PRIVATE-PROFILE-SENTINEL")
    with pytest.raises(CostError) as error:
        validate_profile(value)
    assert "PRIVATE-PROFILE-SENTINEL" not in str(error.value)


@pytest.mark.parametrize("field", ["versions", "fixtureDigests"])
def test_qualified_profile_requires_representative_version_and_fixture(field):
    with pytest.raises(CostError):
        validate_profile(profile(**{field: []}))


def test_registry_has_separate_desktop_and_cli_and_no_implicit_native_qualification():
    from avo.cost_profiles import surface_capabilities

    rows = surface_capabilities()
    assert len(rows) == 10
    assert len({row["environment"] for row in rows}) == 10
    assert {row["surface"] for row in rows if row["agent"] == "codex"} == {
        "cli",
        "desktop",
    }
    assert all(row["capability"] != "qualified" and not row["versions"] for row in rows)
    rows[0]["modes"].clear()
    assert surface_capabilities()[0]["modes"]
