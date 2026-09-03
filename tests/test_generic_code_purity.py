from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
GENERIC_SURFACES = (
    "src/avo/settings.py",
    "src/avo/shorts_paths.py",
    "src/avo/shorts_plan.py",
    "src/avo/shorts_media.py",
    "src/avo/delivery_fidelity.py",
    "src/avo/timeline/picture_lineage.py",
    "src/avo/timeline/materialize.py",
    "src/avo/timeline/review_runner.py",
    "src/avo/adapters/understand/watch_policy.py",
    "src/avo/adapters/understand/watch_skill.py",
    "src/avo/adapters/qc/source_fidelity.py",
)


def _sources() -> dict[str, str]:
    return {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in GENERIC_SURFACES
    }


def test_new_generic_surfaces_contain_no_project_identity_or_private_path() -> None:
    banned = (
        "bishop",
        "nintendo",
        "acjoaobispo",
        "h:\\bishop",
        "c:\\users\\vitor",
        "/home/",
        "talking-head",
    )
    for relative, source in _sources().items():
        lowered = source.casefold()
        for token in banned:
            assert token not in lowered, (
                f"{relative} contains project-specific {token!r}"
            )


def test_watch_prompt_has_no_hardcoded_language_topic_format_or_work_root() -> None:
    source = _sources()["src/avo/adapters/understand/watch_skill.py"].casefold()
    for token in ("pt-br", "portuguese", "tutorial", "talking-head", "youtube-shorts"):
        assert token not in source
    assert "tests/fixtures" not in source


def test_only_explicit_cpu_policy_hides_cuda() -> None:
    source = _sources()["src/avo/adapters/understand/watch_skill.py"]
    assert source.count('"CUDA_VISIBLE_DEVICES": "-1"') == 1
    cpu_branch = source.index('effective.get("device") == "cpu"')
    forced_value = source.index('"CUDA_VISIBLE_DEVICES": "-1"')
    assert abs(forced_value - cpu_branch) < 200


def test_generic_runtime_never_imports_core_data_from_test_fixtures() -> None:
    for relative, source in _sources().items():
        assert "tests.fixtures" not in source, relative
        assert "tests/fixtures" not in source, relative
