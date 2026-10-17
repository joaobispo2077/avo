"""Mutation scope evidence uses actual mutmut outcomes, never profile membership."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "avo_ci_mutation_scopes_test", ROOT / "scripts/ci/mutation_scopes.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "mutation-config.json"
    config.write_text(
        json.dumps(
            {
                "light": {
                    "min_killed_percent": 40,
                    "source_paths": ["src/avo/a.py", "src/avo/b.py"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", config)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for name in ("a", "b"):
        source = tmp_path / f"src/avo/{name}.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"def {name}():\n    return 1\n", encoding="utf-8")
    return module, tmp_path


def metadata(root, name, outcomes):
    path = root / f"mutants/src/avo/{name}.py.meta"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "exit_code_by_key": {
                    f"avo.{name}.x_{name}__mutmut_{index}": outcome
                    for index, outcome in enumerate(outcomes, 1)
                },
                "hash_by_function_name": {},
                "durations_by_key": {},
                "estimated_durations_by_key": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def stats_file(root, **counts):
    path = root / "mutants/mutmut-cicd-stats.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sha": SHA, "run_id": "123", "profile": "light", **counts}),
        encoding="utf-8",
    )
    return path


def capture(module, root, path):
    return module.capture_scopes(
        root=root, stats_path=path, profile="light", sha=SHA, run_id="123"
    )


def validated(module, payload, **aggregate_changes):
    aggregate = {
        "sha": SHA,
        "run_id": "123",
        "profile": "light",
        "floor": 40,
        **payload.get("aggregate", {}).get("counts", {}),
        **aggregate_changes,
    }
    return module.validate_scopes(
        payload, sha=SHA, run_id="123", profile="light", aggregate=aggregate
    )


def test_exports_measured_file_counts_and_hashes_without_new_file_gate(scopes):
    module, root = scopes
    raw_meta = metadata(root, "a", [1, 3, 0])
    metadata(root, "b", [0, 1])
    path = stats_file(root, killed=3, survived=2, total=5)
    payload = capture(module, root, path)
    assert payload["state"] == "MEASURED"
    assert payload["threshold_scope"] == "aggregate"
    assert payload["floor"] == 40
    assert payload["tool"] == {"name": "mutmut", "version": "3.7.0"}
    assert (
        payload["aggregate"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert payload["aggregate"]["artifact_path"] == "mutmut-cicd-stats-light.json"
    first, second = payload["scopes"]
    assert first["score"] == pytest.approx(200 / 3)
    assert second["score"] == 50
    assert first["counts"]["killed"] == 2
    assert first["counts"]["survived"] == 1
    assert (
        first["metadata"]["sha256"] == hashlib.sha256(raw_meta.read_bytes()).hexdigest()
    )
    assert first["metadata"]["artifact_path"] == "scope-evidence/src/avo/a.py.meta"
    assert (
        first["source_sha256"]
        == hashlib.sha256((root / first["path"]).read_bytes()).hexdigest()
    )
    assert "status" not in first
    assert validated(module, payload) == payload


@pytest.mark.parametrize(
    ("relative_root", "relative_stats"), [(False, True), (True, False), (True, True)]
)
def test_capture_normalizes_repository_and_stats_paths(
    scopes, monkeypatch, relative_root, relative_stats
):
    module, root = scopes
    metadata(root, "a", [1])
    metadata(root, "b", [0])
    stats = stats_file(root, killed=1, survived=1, total=2)
    monkeypatch.chdir(root)
    payload = capture(
        module,
        Path(".") if relative_root else root,
        stats.relative_to(root) if relative_stats else stats,
    )
    assert payload["state"] == "MEASURED"
    assert payload["aggregate"]["path"] == "mutants/mutmut-cicd-stats.json"
    assert validated(module, payload) == payload


def test_unknown_and_all_mutmut_outcomes_remain_unresolved(scopes):
    module, root = scopes
    outcomes = [None, 5, 33, 34, 35, 36, 2, 37, -24, 24, 152, 255, -11, -9, 77]
    metadata(root, "a", outcomes)
    metadata(root, "b", [1])
    path = stats_file(
        root,
        killed=1,
        survived=0,
        total=16,
        no_tests=2,
        skipped=1,
        suspicious=2,
        timeout=5,
        check_was_interrupted_by_user=1,
        segfault=2,
    )
    payload = capture(module, root, path)
    assert payload["state"] == "PARTIAL"
    first = payload["scopes"][0]
    assert first["unresolved"] == 15
    assert first["score"] is None
    assert first["counts"]["not_checked"] == 1
    assert first["counts"]["caught_by_type_check"] == 1
    assert first["counts"]["timeout"] == 5  # -24 is timeout, never killed.
    assert first["mutants"][-1]["status"] in module.MUTANT_STATUSES
    assert validated(module, payload) == payload


def test_missing_metadata_retains_only_known_measurements(scopes):
    module, root = scopes
    metadata(root, "a", [1, 0])
    payload = capture(module, root, stats_file(root, killed=2, survived=1, total=3))
    assert payload["state"] == "PARTIAL"
    assert payload["scopes"][0]["score"] == 50
    absent = payload["scopes"][1]
    assert absent["state"] == "UNAVAILABLE"
    assert absent["counts"] is absent["score"] is absent["metadata"] is None
    assert "missing" in absent["reason"].lower()
    assert "reconcil" in payload["reason"].lower()
    assert validated(module, payload) == payload


def test_zero_mutants_are_unavailable_not_a_perfect_result(scopes):
    module, root = scopes
    metadata(root, "a", [])
    metadata(root, "b", [1])
    payload = capture(module, root, stats_file(root, killed=1, survived=0, total=1))
    empty = payload["scopes"][0]
    assert empty["state"] == "UNAVAILABLE"
    assert empty["counts"]["total"] == 0
    assert empty["score"] is None
    assert "zero" in empty["reason"].lower()


@pytest.mark.parametrize("change", [{"killed": 9}, {"total": 9}, {"survived": -1}])
def test_rejects_aggregate_discrepancies_and_malformed_counts(scopes, change):
    module, root = scopes
    metadata(root, "a", [1])
    metadata(root, "b", [0])
    payload = capture(module, root, stats_file(root, killed=1, survived=1, total=2))
    with pytest.raises(ValueError):
        validated(module, payload, **change)


@pytest.mark.parametrize(
    "field,value", [("sha", "b" * 40), ("run_id", "old"), ("profile", "full")]
)
def test_rejects_stale_export_identity(scopes, field, value):
    module, root = scopes
    path = stats_file(root, killed=0, survived=0, total=0)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[field] = value
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        capture(module, root, path)


@pytest.mark.parametrize(
    "unsafe", ["../a.py", "src/avo/../a.py", "C:/a.py", "src\\avo\\a.py"]
)
def test_rejects_unsafe_profile_source_paths(scopes, unsafe):
    module, root = scopes
    config = json.loads(module.CONFIG_PATH.read_text(encoding="utf-8"))
    config["light"]["source_paths"] = [unsafe]
    module.CONFIG_PATH.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="path"):
        capture(module, root, stats_file(root, killed=0, survived=0, total=0))


def test_rejects_duplicate_json_mutants_and_wrong_source_identity(scopes):
    module, root = scopes
    path = metadata(root, "a", [1])
    metadata(root, "b", [0])
    stats = stats_file(root, killed=1, survived=1, total=2)
    path.write_text(
        '{"exit_code_by_key":{"avo.a.x_a__mutmut_1":1,"avo.a.x_a__mutmut_1":0}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        capture(module, root, stats)
    path.write_text(
        '{"exit_code_by_key":{"avo.other.x_a__mutmut_1":1}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="mutant"):
        capture(module, root, stats)


@pytest.mark.parametrize(
    "tamper",
    [
        "score",
        "count",
        "aggregate_count",
        "unresolved",
        "exit",
        "path",
        "hash",
        "floor",
        "population",
    ],
)
def test_validator_recomputes_all_derived_fields_and_provenance(scopes, tamper):
    module, root = scopes
    metadata(root, "a", [1])
    metadata(root, "b", [0])
    payload = capture(module, root, stats_file(root, killed=1, survived=1, total=2))
    payload = copy.deepcopy(payload)
    if tamper == "score":
        payload["scopes"][0]["score"] = 0
    elif tamper == "count":
        payload["scopes"][0]["counts"]["killed"] = True
    elif tamper == "aggregate_count":
        payload["aggregate"]["counts"]["killed"] = True
    elif tamper == "unresolved":
        payload["scopes"][0]["unresolved"] = False
    elif tamper == "exit":
        payload["scopes"][0]["mutants"][0]["exit_code"] = 0
    elif tamper == "path":
        payload["scopes"][0]["metadata"]["path"] = "../escape.meta"
    elif tamper == "hash":
        payload["scopes"][0]["source_sha256"] = "bad"
    elif tamper == "floor":
        payload["floor"] = 80
    else:
        payload["scopes"].pop()
    with pytest.raises(ValueError):
        validated(module, payload, killed=1)


@pytest.mark.parametrize("outcome", [True, False, "1", 1.5, [], {}])
def test_malformed_metadata_exit_codes_are_rejected(scopes, outcome):
    module, root = scopes
    metadata(root, "a", [outcome])
    metadata(root, "b", [])
    with pytest.raises(ValueError, match="outcome"):
        capture(module, root, stats_file(root, killed=1, survived=0, total=1))


def test_complete_metadata_population_must_reconcile_before_export(scopes):
    module, root = scopes
    metadata(root, "a", [1])
    metadata(root, "b", [0])
    with pytest.raises(ValueError, match="reconcile"):
        capture(module, root, stats_file(root, killed=2, survived=1, total=3))


def test_duplicate_profile_paths_are_rejected(scopes):
    module, root = scopes
    config = json.loads(module.CONFIG_PATH.read_text(encoding="utf-8"))
    config["light"]["source_paths"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        module.capture_scopes(
            root=root,
            stats_path=stats_file(root, killed=0, survived=0, total=0),
            profile="light",
            sha=SHA,
            run_id="123",
            config=config,
        )


def test_cli_overwrites_stale_scope_file_with_honest_diagnostic(scopes, monkeypatch):
    module, root = scopes
    output = root / "reports/mutation/mutation-scopes.json"
    output.parent.mkdir(parents=True)
    output.write_text('{"state":"MEASURED"}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    assert (
        module.main(
            [
                "--stats",
                str(root / "absent.json"),
                "--profile",
                "light",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["state"] == "UNAVAILABLE"
    assert payload["scopes"] == []
    assert payload["reason"]
    assert validated(module, payload)["state"] == "UNAVAILABLE"


@pytest.mark.parametrize("relative_paths", [False, True])
def test_cli_retains_exact_metadata_bytes_for_independent_verification(
    scopes, monkeypatch, relative_paths
):
    module, root = scopes
    metadata(root, "a", [1])
    metadata(root, "b", [0])
    stats = stats_file(root, killed=1, survived=1, total=2)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    output = root / "reports/mutation/mutation-scopes.json"
    monkeypatch.chdir(root)
    stats_arg = stats.relative_to(root) if relative_paths else stats
    output_arg = output.relative_to(root) if relative_paths else output
    assert (
        module.main(
            ["--stats", str(stats_arg), "--profile", "light", "--out", str(output_arg)]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["state"] == "MEASURED"
    for row in payload["scopes"]:
        original = root / row["metadata"]["path"]
        archived = output.parent / row["metadata"]["artifact_path"]
        assert original.read_bytes() == archived.read_bytes()
        assert (
            hashlib.sha256(archived.read_bytes()).hexdigest()
            == row["metadata"]["sha256"]
        )


def test_cli_rejects_metadata_changes_during_capture(scopes, monkeypatch):
    module, root = scopes
    meta = metadata(root, "a", [1])
    metadata(root, "b", [0])
    stats = stats_file(root, killed=1, survived=1, total=2)
    original = module.capture_scopes

    def changed(**kwargs):
        payload = original(**kwargs)
        meta.write_text("{}", encoding="utf-8")
        return payload

    monkeypatch.setattr(module, "capture_scopes", changed)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    output = root / "reports/mutation/mutation-scopes.json"
    assert (
        module.main(["--stats", str(stats), "--profile", "light", "--out", str(output)])
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["state"] == "UNAVAILABLE"
    assert "changed" in payload["reason"]


def test_both_runners_export_scopes_after_successful_stamp_before_gate():
    for name in ("run-mutation-light.sh", "quality-mutation.sh"):
        text = (ROOT / "scripts/ci" / name).read_text(encoding="utf-8")
        assert text.index("mutmut run") < text.index("mutmut export-cicd-stats")
        assert text.index("mutmut export-cicd-stats") < text.index("--stamp")
        assert text.index("--stamp") < text.index("mutation_scopes.py")
        assert text.index("mutation_scopes.py") < text.index("check_mutation.py")
        assert text.index("mutmut run") < text.index(
            "rm -f mutants/mutmut-cicd-stats.json"
        )
        assert text.index("rm -f mutants/mutmut-cicd-stats.json") < text.index(
            "mutmut export-cicd-stats"
        )
        assert text.index("rm -f reports/mutation/mutation-scopes.json") < text.index(
            "mutmut run"
        )
