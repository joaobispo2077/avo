"""Explicit imported previews retain exact omissions and cannot waive timing."""

from copy import deepcopy

import pytest

from avo.timeline.resolve_export import import_approximation, require_renderable_import
from tests.test_timeline_import_layout import placed_snapshot


def unresolved_snapshot():
    snapshot = placed_snapshot()
    snapshot["sources"][0]["streamMetadata"] = {"videoClock": {"status": "verified"}}
    layout = snapshot["layout"]
    layout["importMode"] = "export-driven"
    owner = layout["placements"][0]["elementId"]
    layout["resolveEffects"] = [
        {
            "pointer": owner + "/effects/0",
            "ownerPointer": owner,
            "name": "Unknown cropping",
            "state": "unresolved",
            "payload": {"OTIO_SCHEMA": "Effect.1"},
            "evidenceOrigin": "export",
        }
    ]
    return snapshot


def test_explicit_approximation_accounts_for_effects_without_mutating_canonical_data():
    snapshot = unresolved_snapshot()
    before = deepcopy(snapshot)
    declaration = import_approximation(
        snapshot, authorization="User selected a short approximation first"
    )
    require_renderable_import(snapshot, approximation=declaration, preview_only=True)
    assert snapshot == before
    assert declaration["omittedEffects"] == [
        {
            "pointer": snapshot["layout"]["resolveEffects"][0]["pointer"],
            "name": "Unknown cropping",
        }
    ]
    with pytest.raises(ValueError, match="unsupported"):
        require_renderable_import(snapshot)


@pytest.mark.parametrize(
    "defect", ["full-proof", "missing-effect", "changed-name", "changed-pointer"]
)
def test_preview_policy_cannot_be_promoted_or_forged(defect):
    snapshot = unresolved_snapshot()
    declaration = import_approximation(
        snapshot, authorization="User chose approximation"
    )
    preview = defect != "full-proof"
    if defect == "missing-effect":
        declaration["omittedEffects"] = []
    elif defect == "changed-name":
        declaration["omittedEffects"][0]["name"] = "Something else"
    elif defect == "changed-pointer":
        declaration["omittedEffects"][0]["pointer"] = "/unrelated"
    with pytest.raises(ValueError, match="preview-only|stale|unaccounted"):
        require_renderable_import(
            snapshot, approximation=declaration, preview_only=preview
        )


@pytest.mark.parametrize("defect", ["clock", "generator", "authorization"])
def test_approximation_does_not_waive_unqualified_sources_or_missing_authorization(
    defect,
):
    snapshot = unresolved_snapshot()
    if defect == "clock":
        snapshot["sources"][0]["streamMetadata"]["videoClock"]["status"] = "unverified"
    elif defect == "generator":
        snapshot["layout"]["placements"][0]["mediaKind"] = "generator"
    with pytest.raises(ValueError, match="authorization|clocks|generated"):
        import_approximation(
            snapshot,
            authorization=""
            if defect == "authorization"
            else "User chose approximation",
        )
