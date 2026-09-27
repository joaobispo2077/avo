from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline import provider_animation
from avo.timeline.animation import AnimationError
from avo.timeline.contracts import content_hash
from avo.timeline.provider_animation import ProviderAnimationService
from tests.test_animation_promotion import pattern
from tests.test_provider_animation_promotion import _propose


def _approve(tmp_path: Path):
    proposal = _propose(tmp_path, "export const component = ({label}) => label")
    service = ProviderAnimationService(
        tmp_path / "provider" / "animations" / "animation.json",
        provider="example",
        clock=lambda: "2026-08-13T00:00:00Z",
    )
    event = service.decide(
        Path(proposal["path"]),
        decision="approved",
        actor="creator",
        reason="reviewed",
        expected_catalog_sha256=content_hash(service.initialize()),
    )
    return service, proposal, event


def test_atomic_version_publication_is_immutable_idempotent_and_cas_guarded(
    tmp_path: Path,
):
    service, proposal, event = _approve(tmp_path)
    published = Path(event["publishedPath"])
    assert (published / "manifest.json").is_file()
    assert (
        service.decide(
            Path(proposal["path"]), decision="approved", actor="creator", reason="retry"
        )["idempotent"]
        is True
    )

    document = json.loads(Path(proposal["path"]).read_text(encoding="utf-8"))
    document["kit"]["files"][0]["content"] += "\n// tampered"
    Path(proposal["path"]).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(AnimationError, match="proposal hash"):
        service.decide(
            Path(proposal["path"]), decision="approved", actor="creator", reason="bad"
        )
    with pytest.raises(AnimationError, match="compare-and-swap"):
        service.reject_recommendation(
            pattern_id="c01-c02",
            evidence_sha256="b" * 64,
            actor="creator",
            reason="no",
            expected_catalog_sha256="0" * 64,
        )


def test_deprecation_retains_exact_version_and_upgrade_is_opt_in(tmp_path: Path):
    service, _, event = _approve(tmp_path)
    before = Path(event["publishedPath"])
    service.deprecate(
        "c01-c02", "1.0.0", actor="creator", reason="new version available"
    )
    assert before.is_dir()
    assert service.resolve_version("c01-c02", "1.0.0")["status"] == "deprecated"
    with pytest.raises(AnimationError, match="opt-in"):
        service.resolve_version("c01-c02", "1.0.0", upgrade_to="2.0.0")


@pytest.mark.parametrize(
    ("version", "change_type", "accepted"),
    [("1.0.1", "patch", True), ("1.1.0", "minor", True), ("1.1.0", "major", False)],
)
def test_semantic_version_matches_declared_compatibility(
    tmp_path: Path, version: str, change_type: str, accepted: bool
):
    service, _, _ = _approve(tmp_path)
    next_pattern = pattern()
    next_pattern["version"] = version
    proposal = _propose(
        tmp_path,
        f"export const version = '{version}'",
        pattern_value=next_pattern,
        change_type=change_type,
    )
    action = lambda: service.decide(
        Path(proposal["path"]),
        decision="approved",
        actor="creator",
        reason="reviewed",
    )
    if accepted:
        assert action()["type"] == "promotion-approved"
    else:
        with pytest.raises(AnimationError, match="semantic version"):
            action()


def test_same_version_changed_bytes_are_rejected(tmp_path: Path):
    service, _, _ = _approve(tmp_path)
    proposal = _propose(tmp_path, "export const component = () => 'different'")
    with pytest.raises(AnimationError, match="immutable semantic version"):
        service.decide(
            Path(proposal["path"]),
            decision="approved",
            actor="creator",
            reason="must bump version",
        )


def test_catalog_write_failure_rolls_back_uncommitted_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    proposal = _propose(tmp_path, "export const component = () => 'neutral'")
    service = ProviderAnimationService(
        tmp_path / "provider" / "animations" / "animation.json", provider="example"
    )
    service.initialize()
    original = provider_animation.atomic_write_json

    def fail_catalog(path, value):
        if Path(path) == service.path:
            raise OSError("simulated catalog failure")
        return original(path, value)

    monkeypatch.setattr(provider_animation, "atomic_write_json", fail_catalog)
    with pytest.raises(OSError, match="simulated"):
        service.decide(
            Path(proposal["path"]),
            decision="approved",
            actor="creator",
            reason="approved",
        )
    assert not (
        service.path.parent / "hyperframes" / "c01-c02" / "versions" / "1.0.0"
    ).exists()
