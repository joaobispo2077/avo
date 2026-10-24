"""Real generic definitions and installed-resource declaration boundaries."""

from __future__ import annotations

import importlib.resources
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from avo.timeline.contracts import document_hash_excluding, validate_document

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/avo/resources/directions/catalog.json"
EXPECTED = {
    "analysis-review",
    "step-by-step",
    "narrative-conversation",
    "focused-short",
}


def definitions() -> list[dict]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["schemaVersion"] == "1.0.0"
    return catalog["directions"]


def test_definitions_cover_four_distinct_contexts_with_exact_valid_identity():
    values = definitions()
    assert {value["builtinId"] for value in values} == EXPECTED
    assert len(values) == 4
    for value in values:
        validate_document(value, "avo.direction.schema.json#/$defs/BuiltinDirection")
        assert value["version"] == "1.0.0"
        assert value["documentHash"] == document_hash_excluding(value, "documentHash")
        assert value["createdBy"]["type"] != "human"
        assert value["formats"] and value["viewerIntents"]
        assert value["promiseGuidance"] and value["sectionGuidance"]
        assert all(value[field] for field in ("rhythm", "visual", "motion", "sound"))
        assert value["variants"] and value["exclusions"] and value["constraints"]


@pytest.mark.parametrize("identifier", sorted(EXPECTED))
def test_definition_has_portable_doctrine_and_reading_accessibility_limits(identifier):
    value = next(item for item in definitions() if item["builtinId"] == identifier)
    assert value["doctrineRefs"]
    assert all(isinstance(ref, str) and ref.strip() for ref in value["doctrineRefs"])
    assert any("sha256:" in ref for ref in value["doctrineRefs"])
    visible = " ".join(
        [*value["constraints"], *value["exclusions"], *value["sectionGuidance"]]
    ).casefold()
    assert any(word in visible for word in ("read", "reading", "legib"))
    assert any(word in visible for word in ("meaning", "factual", "intent"))
    assert any(word in visible for word in ("flash", "accessib", "motion"))
    assert "\u2014" not in visible


def test_definitions_are_generic_and_do_not_encode_historical_audio_or_cuts():
    text = CATALOG.read_text(encoding="utf-8").casefold()
    for private in ("bishop", "vitor", "nintendo", "qual a dura", "learndown-v002"):
        assert private not in text
    assert not re.search(r"[a-z]:[\\/]", text)
    assert not re.search(r"\b(?:nr\s*30|afftdn|lufs|-26\s*db|1\.5\s*[x×])", text)
    for value in definitions():
        assert "approval" not in value and "media" not in value


def test_installed_resources_are_declared_in_package_data():
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(
        r'"avo\.resources\.directions"\s*=\s*\[[^\]]*"\*?[^"\]]*\.json"',
        configuration,
    ), "Package data must explicitly carry the real built-in JSON catalog"


def test_installed_discovery_does_not_depend_on_current_checkout_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    resource = importlib.resources.files("avo.resources.directions").joinpath(
        "catalog.json"
    )
    actual = json.loads(resource.read_text(encoding="utf-8"))
    assert {item["builtinId"] for item in actual["directions"]} == EXPECTED
    assert actual["directions"] == definitions()


@pytest.fixture(scope="module")
def installed_direction_package(tmp_path_factory):
    """Build/install offline into a temporary target, never the user's environment."""
    work = tmp_path_factory.mktemp("direction-distribution")
    source = work / "source"
    source.mkdir()
    for filename in ("pyproject.toml", "LICENSE"):
        shutil.copyfile(ROOT / filename, source / filename)
    shutil.copytree(
        ROOT / "src/avo",
        source / "src/avo",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(ROOT / "schemas", source / "schemas")
    wheel_dir = work / "wheels"
    target = work / "installed"
    outside = work / "outside-checkout"
    outside.mkdir()
    environment = {
        **os.environ,
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    environment.pop("AVO_ROOT", None)
    environment.pop("PYTHONPATH", None)

    def run(arguments, *, cwd=outside, env=environment):
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", *arguments],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return completed

    run(
        [
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
            "--wheel-dir",
            str(wheel_dir),
            str(source),
        ]
    )
    wheels = list(wheel_dir.glob("avo-*.whl"))
    assert len(wheels) == 1
    run(
        [
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            "--no-cache-dir",
            "--target",
            str(target),
            str(wheels[0]),
        ]
    )
    installed_environment = {**environment, "PYTHONPATH": str(target)}
    return target, outside, installed_environment, run


@pytest.mark.integration
def test_real_wheel_resolves_exact_resources_and_schemas_without_checkout(
    installed_direction_package,
):
    target, outside, environment, run = installed_direction_package
    probe = """
import json,sys
from pathlib import Path
from importlib.resources import files
import avo
from avo.paths import schema_path
from avo.direction.rules import validate
target=Path(sys.argv[1]).resolve()
assert Path(avo.__file__).resolve().is_relative_to(target), avo.__file__
catalog=json.loads(files('avo.resources.directions').joinpath('catalog.json').read_text(encoding='utf-8'))
for item in catalog['directions']:
    validate('BuiltinDirection',item)
for name in ('avo.direction.schema.json','avo.briefstart.schema.json'):
    assert schema_path(name).resolve().is_relative_to(target), schema_path(name)
print(json.dumps({'ids':[item['builtinId'] for item in catalog['directions']]}))
"""
    completed = run(["-c", probe, str(target)], cwd=outside, env=environment)
    assert set(json.loads(completed.stdout)["ids"]) == EXPECTED


@pytest.mark.integration
def test_real_installed_engine_entry_uses_creative_aliases_without_media(
    installed_direction_package,
):
    _, outside, environment, run = installed_direction_package
    catalog = run(["-m", "avo", "direction", "catalog", "--json"], env=environment)
    assert len(json.loads(catalog.stdout)["builtins"]) == 4
    raw = outside / "new-video"
    raw.mkdir()
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "neutral", "videoId": "distribution-smoke", "rawDir": str(raw)}
        ),
        encoding="utf-8",
    )
    shown = run(
        ["-m", "avo", "briefstart", "show", "--project", str(project), "--json"],
        env=environment,
    )
    assert json.loads(shown.stdout)["status"] == "bypassed"
    assert not (raw / "edit/briefstart").exists()
