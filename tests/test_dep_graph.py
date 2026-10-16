"""Dependency diagnostics resolve real local imports and never hide parse failures."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "avo_dep_graph", ROOT / "scripts/ci/avo_dep_graph.py"
)
assert SPEC and SPEC.loader
GRAPH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAPH)


def _source(root: Path, files: dict[str, str]) -> Path:
    source = root / "src" / "avo"
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return source


def test_resolves_aliases_root_submodules_and_relative_imports(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        {
            "__init__.py": "",
            "alpha.py": ("import avo.beta as beta, avo.gamma\nimport avoiding, json\n"),
            "root_imports.py": "from avo import beta, gamma\n",
            "symbols.py": "from avo.beta import TOKEN\n",
            "beta.py": "TOKEN = 1\n",
            "gamma.py": "",
            "isolated.py": "",
            "nested/__init__.py": "from .. import beta\n",
            "nested/deep.py": (
                "from .. import gamma\n"
                "from . import helper\n"
                "from .helper import marker\n"
                "from ..alpha import beta\n"
            ),
            "nested/helper.py": "marker = 1\n",
        },
    )
    nodes, edges = GRAPH.collect_edges(source)
    assert nodes == {
        "avo",
        "avo.alpha",
        "avo.beta",
        "avo.gamma",
        "avo.isolated",
        "avo.nested",
        "avo.root_imports",
        "avo.symbols",
    }
    assert edges == {
        ("avo.alpha", "avo.beta"),
        ("avo.alpha", "avo.gamma"),
        ("avo.nested", "avo.alpha"),
        ("avo.nested", "avo.beta"),
        ("avo.nested", "avo.gamma"),
        ("avo.root_imports", "avo.beta"),
        ("avo.root_imports", "avo.gamma"),
        ("avo.symbols", "avo.beta"),
    }


def test_package_attributes_and_namespace_packages(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        {
            "__init__.py": "VALUE = 1\n",
            "consumer.py": "from avo import VALUE\nimport avo.namespace\n",
            "namespace/helper.py": "",
        },
    )
    nodes, edges = GRAPH.collect_edges(source)
    assert "avo.namespace" in nodes
    assert edges == {
        ("avo.consumer", "avo"),
        ("avo.consumer", "avo.namespace"),
    }


@pytest.mark.parametrize(
    "statement", ["import avo.missing", "from avo.missing import value"]
)
def test_unresolved_internal_import_has_source_location(
    tmp_path: Path, statement: str
) -> None:
    source = _source(tmp_path, {"__init__.py": "", "bad.py": statement})
    with pytest.raises(ValueError, match=r"bad\.py:1.*avo\.missing"):
        GRAPH.collect_edges(source)


def test_invalid_relative_import_has_source_location(tmp_path: Path) -> None:
    source = _source(tmp_path, {"__init__.py": "", "bad.py": "from .. import value"})
    with pytest.raises(ValueError, match=r"bad\.py:1.*relative"):
        GRAPH.collect_edges(source)


def test_syntax_and_encoding_failures_are_not_skipped(tmp_path: Path) -> None:
    source = _source(tmp_path, {"bad.py": "def broken(:"})
    with pytest.raises(SyntaxError) as error:
        GRAPH.collect_edges(source)
    assert error.value.filename == str(source / "bad.py")
    assert error.value.lineno == 1
    (source / "bad.py").write_bytes(b"\xff")
    with pytest.raises(ValueError, match=r"bad\.py.*UTF-8"):
        GRAPH.collect_edges(source)


def test_missing_source_fails_instead_of_reporting_an_empty_graph(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        GRAPH.collect_edges(tmp_path / "missing")


def test_html_is_self_contained_and_includes_isolated_packages(tmp_path: Path) -> None:
    nodes = {"avo.alpha", "avo.beta", "avo.isolated", "avo.<unsafe>"}
    edges = {("avo.beta", "avo.alpha")}
    provenance = {
        "sha": "a" * 40,
        "recorded_at": "2026-10-14T12:00:00Z",
        "scope": "src/avo/**/*.py",
    }
    output = tmp_path / "avo-imports.html"
    GRAPH.write_html(nodes, edges, output, provenance=provenance)
    html = output.read_text(encoding="utf-8")
    assert '<meta name="viewport"' in html
    assert "<table>" in html
    assert '<th scope="row">avo.isolated</th>' in html
    assert 'href="avo-imports.dot"' in html
    assert "Depends on" in html and "Used by" in html
    assert "avo.&lt;unsafe&gt;" in html
    assert "avo.<unsafe>" not in html
    assert "a" * 40 in html and provenance["recorded_at"] in html
    assert provenance["scope"] in html
    assert "flowchart LR" not in html and "<script" not in html
    assert "https://" not in html and "http://" not in html


def test_dot_is_sorted_and_keeps_isolated_packages(tmp_path: Path) -> None:
    output = tmp_path / "avo-imports.dot"
    GRAPH.write_dot(
        {"avo.isolated", "avo.beta", "avo.alpha"},
        {("avo.beta", "avo.alpha"), ("avo.alpha", "avo.beta")},
        output,
    )
    dot = output.read_text(encoding="utf-8")
    assert dot.index('"avo.alpha";') < dot.index('"avo.beta";')
    assert dot.index('"avo.alpha" ->') < dot.index('"avo.beta" ->')
    assert '"avo.isolated";' in dot


def test_main_records_commit_utc_and_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = _source(tmp_path, {"__init__.py": "", "isolated.py": ""})
    monkeypatch.setattr(GRAPH, "SRC", source)
    monkeypatch.setattr(GRAPH, "OUT_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        GRAPH.subprocess, "check_output", lambda *args, **kwargs: "b" * 40
    )
    assert GRAPH.main() == 0
    summary = json.loads((GRAPH.OUT_DIR / "summary.json").read_text(encoding="utf-8"))
    assert summary["sha"] == "b" * 40
    assert summary["scope"] == "src/avo/**/*.py"
    assert summary["nodes"] == 2 and summary["edges"] == 0
    assert datetime.fromisoformat(summary["recorded_at"].replace("Z", "+00:00")).tzinfo
    html = (GRAPH.OUT_DIR / "avo-imports.html").read_text(encoding="utf-8")
    assert summary["sha"] in html and summary["recorded_at"] in html


def test_main_reports_errors_without_creating_a_partial_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    source = _source(tmp_path, {"bad.py": "def broken(:"})
    monkeypatch.setattr(GRAPH, "SRC", source)
    monkeypatch.setattr(GRAPH, "OUT_DIR", tmp_path / "reports")
    assert GRAPH.main() == 1
    assert "bad.py:1" in capsys.readouterr().err
    assert not GRAPH.OUT_DIR.exists()
