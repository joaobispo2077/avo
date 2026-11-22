"""Keep documented application capabilities separate from verified operations."""

from datetime import date
from types import SimpleNamespace

import pytest

from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.artcraft_native_cli import observe_native_command_schema
from avo.artcraft import ArtCraftError, catalog
from avo.timeline.contracts import file_fingerprint

_REQUIRED_FAMILIES = {
    "anicraft": {
        "keyframes",
        "classic-shape-tweens",
        "symbols",
        "nested-scenes",
        "frame-sprite-lottie-video-export",
    },
    "effectcraft": {
        "layered-composition",
        "mattes",
        "masks",
        "keyframes",
        "text",
        "render-queue",
    },
    "filmcraft": {
        "timeline-editing",
        "multicam",
        "audio-effects-mix-automation",
        "timeline-interchange",
    },
    "soundcraft": {
        "audio-editing-playlists",
        "mixing-routing",
        "built-in-external-effects",
        "audio-bounce",
    },
    "vectorcraft": {
        "path-edit-combine",
        "paint-color-materials",
        "type-spelling",
        "data-graphs-variables",
    },
    "photocraft": {
        "layers-masks-smart-objects",
        "nondestructive-adjustment",
        "color-depth-profiles",
    },
    "lightcraft": {
        "organization-search",
        "development-color-detail",
        "presets-profiles",
    },
    "figcraft": {"layout-constraints", "components-variants-properties", "prototypes"},
    "texturecraft": {"materials", "mesh-map-baking", "texture-channel-packed-export"},
    "deckcraft": {"masters-layouts-themes", "transitions-animation", "presenter-tools"},
}

_WINDOWS_RELEASES = {
    "anicraft": "0.2.1",
    "effectcraft": "0.24.1",
    "filmcraft": "0.20.1",
    "soundcraft": "0.20.1",
    "vectorcraft": "0.24.1",
    "photocraft": "0.23.1",
    "lightcraft": "0.21.1",
    "figcraft": "0.18.1",
    "deckcraft": "0.18.1",
}


@pytest.mark.parametrize("app", _REQUIRED_FAMILIES)
def test_catalog_has_evidence_and_capabilities_for_each_app(app):
    data = catalog(app=app)
    (profile,) = data["profiles"]
    assert _REQUIRED_FAMILIES[app] <= set(profile["families"])
    assert date.fromisoformat(profile.get("retrievedOn", data["retrievedOn"]))
    assert profile["sources"] and all(
        url.startswith("https://") for url in profile["sources"]
    )
    assert set(profile["documentedModes"]).isdisjoint(profile["unverifiedModes"])
    assert profile["claimedState"] == "documented-only"
    qualified = profile["qualifiedProfiles"]
    if app == "texturecraft":
        assert qualified == []
        return
    identities = {(case["behavior"], case["mode"]) for case in qualified}
    assert len(identities) == len(qualified) and qualified
    for case in qualified:
        assert case["behavior"] in profile["operations"]
        assert case["release"] == _WINDOWS_RELEASES[app]
        assert case["platform"] == "windows"
        assert case["mode"] in profile["documentedModes"]
        assert case["requiredAuthority"] in {"independently-confined", "operator"}
        assert date.fromisoformat(case["verifiedOn"])
        assert catalog(app=app, behavior=case["behavior"])["profiles"] == [profile]


def test_documented_live_mode_cannot_launch_an_unqualified_profile(
    tmp_path, monkeypatch
):
    from avo.adapters import artcraft as adapter_module

    (profile,) = catalog(app="deckcraft")["profiles"]
    assert "live" in profile["documentedModes"]
    monkeypatch.setattr(
        adapter_module,
        "_installed_tools",
        lambda *_: pytest.fail("Probed an unready mode"),
    )
    with pytest.raises(ArtCraftError, match="requires a confined CLI runner"):
        SelectedArtCraftAdapter(lambda *_: {}, lambda *_: b"").observe(
            scope={"app": "deckcraft", "operations": ["editable-explanation-slide"]},
            mode="live",
            roots={"read": [], "write": [str(tmp_path)]},
            cli_path=None,
            app_path=None,
        )


def test_selected_registry_rejects_a_binary_changed_during_observation(
    tmp_path, monkeypatch
):
    from avo.adapters import artcraft_native_cli

    cli = tmp_path / "photocraft-cli"
    cli.write_bytes(b"initial tool")
    fingerprint = file_fingerprint(cli)

    def changed(*_args, **_kwargs):
        cli.write_bytes(b"different native tool")
        return SimpleNamespace(stdout=b'[{"id":"layer.hideLayers","params":"{}"}]')

    monkeypatch.setattr(artcraft_native_cli.subprocess, "run", changed)
    with pytest.raises(ArtCraftError, match="scope or executable changed"):
        observe_native_command_schema(
            fingerprint, {}, needed={"layer.hideLayers"}, label="PhotoCraft"
        )
