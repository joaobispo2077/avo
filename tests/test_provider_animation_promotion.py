from __future__ import annotations

from pathlib import Path

import pytest

from avo.timeline.animation import AnimationError
from avo.timeline.provider_animation import ProviderAnimationService
from tests.test_animation_promotion import pattern


def _rights() -> list[dict]:
    return [
        {
            "dependencyId": "runtime",
            "sha256": "a" * 64,
            "owner": "AVO",
            "source": "repository",
            "license": "MIT",
            "evidenceRef": "rights/runtime.json",
            "derivativesAllowed": True,
            "providerWide": True,
            "commercialUse": True,
            "attribution": "none",
            "territory": "worldwide",
            "termEndsAt": None,
            "revoked": False,
            "aiDisclosure": "none",
        }
    ]


def _propose(
    tmp_path: Path,
    source: str,
    *,
    authorized: bool = False,
    pattern_value: dict | None = None,
    change_type: str = "major",
):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / "component.js").write_text(source, encoding="utf-8")
    reusable_pattern = pattern_value or pattern()
    reusable_pattern["behavior"].setdefault(
        "lifecycle",
        {
            "preEntry": "hidden",
            "entrance": "fade",
            "hold": "readable",
            "exit": "fade",
        },
    )
    service = ProviderAnimationService(
        tmp_path / "provider" / "animations" / "animation.json",
        provider="example",
        clock=lambda: "2026-08-13T00:00:00Z",
    )
    return service.propose_from_project(
        reusable_pattern,
        project_root=root,
        selected_files=["component.js"],
        parameter_schema={"type": "object", "properties": {}},
        dependency_lock={"runtime": {"version": "1.0.0", "sha256": "a" * 64}},
        rights=_rights(),
        fixtures=[
            {"fixtureId": "neutral-a", "parameters": {}, "reducedMotion": False},
            {"fixtureId": "neutral-b", "parameters": {}, "reducedMotion": True},
        ],
        actor="creator",
        intent_reference="explicit reusable component request",
        visible_text_authorized=authorized,
        change_type=change_type,
        validator=lambda operation, _root, fixture: (
            f"{operation}:{(fixture or {}).get('fixtureId', 'project')}"
        ),
    )


@pytest.mark.parametrize(
    "source",
    [
        "import x from 'C:/private/module.js'",
        "const x = 'file:///private/component.js'",
        ".x { background: url(secret.png) }",
        "//# sourceMappingURL=component.js.map",
        "const API_KEY = 'secret-value'",
        "fetch('https://example.test/data')",
        "const timestamp = '00:01:02.003'",
        "const footage = 'take-01.mp4'",
        "const title = 'private — project claim'",
    ],
)
def test_proposal_rejects_project_leaks_and_render_network(tmp_path: Path, source: str):
    with pytest.raises(AnimationError):
        _propose(tmp_path, source)


def test_visible_text_em_dash_requires_explicit_authorization(tmp_path: Path):
    proposal = _propose(
        tmp_path,
        "export const title = 'neutral — authorized fixture'",
        authorized=True,
    )
    assert proposal["sanitizationReport"]["visibleTextAuthorized"] is True
    assert proposal["generalizability"]["eligible"] is True


def test_proposal_rejects_nondeterministic_fixture_render(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "component.js").write_text("export const x = 1", encoding="utf-8")
    calls = iter(["first", "second"])

    def validator(operation, _root, _fixture):
        return next(calls) if operation == "render" else "ok"

    service = ProviderAnimationService(tmp_path / "animation.json", provider="example")
    reusable_pattern = pattern()
    reusable_pattern["behavior"]["lifecycle"] = {
        "preEntry": "hidden",
        "entrance": "fade",
        "hold": "readable",
        "exit": "fade",
    }
    with pytest.raises(AnimationError, match="deterministic"):
        service.propose_from_project(
            reusable_pattern,
            project_root=root,
            selected_files=["component.js"],
            parameter_schema={"type": "object"},
            dependency_lock={"runtime": {"version": "1", "sha256": "a" * 64}},
            rights=_rights(),
            fixtures=[
                {"fixtureId": "a", "parameters": {}, "reducedMotion": False},
                {"fixtureId": "b", "parameters": {}, "reducedMotion": True},
            ],
            actor="creator",
            intent_reference="explicit",
            validator=validator,
        )
