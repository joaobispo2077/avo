"""Packager contract (aeb-021). No freeze, no GitHub, no pip install avo."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = (ROOT / "packaging" / "avo.spec").read_text(encoding="utf-8")
SH = (ROOT / "scripts" / "ci" / "build-engine.sh").read_text(encoding="utf-8")
PS1 = (ROOT / "scripts" / "ci" / "build-engine.ps1").read_text(encoding="utf-8")


def test_spec_is_onedir_not_onefile() -> None:
    assert "exclude_binaries=True" in SPEC
    assert "COLLECT(" in SPEC
    assert "onefile=True" not in SPEC
    assert "Forbidden: PyOxidizer" in SPEC
    assert "--onefile" not in SH
    assert "--onefile" not in PS1


def test_spec_bundles_config_schemas_templates() -> None:
    assert '"config"' in SPEC
    assert '"schemas"' in SPEC
    assert "shorts_hyperframes" in SPEC
    assert 'collect_all("avo")' in SPEC or '_collect("avo")' in SPEC


def test_spec_bundles_direction_resources_and_new_schema_contracts() -> None:
    assert 'collect_data_files("avo.resources.directions")' in SPEC
    assert '"avo.resources.directions"' in SPEC
    assert '(str(REPO_ROOT / "schemas"), "schemas")' in SPEC
    for name in ("avo.direction.schema.json", "avo.briefstart.schema.json"):
        assert (ROOT / "schemas" / name).is_file()


def test_python_distribution_declares_runtime_schema_data() -> None:
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.data-files]" in configuration
    assert '"share/avo/schemas" = ["schemas/*.json"]' in configuration


def test_library_review_resources_are_packaged_and_available():
    import tomllib
    from importlib import resources

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["tool"]["setuptools"]["package-data"][
        "avo.templates.library_review"
    ]
    assets = resources.files("avo.templates.library_review")
    for name in ("index.html", "review.css", "review.js"):
        assert assets.joinpath(name).is_file()
    assert (ROOT / "schemas/avo.library.schema.json").is_file()
    assert ("collect_data_files", "avo.templates.library_review") in _packaging_calls()


def test_frozen_library_worker_has_native_dispatch_without_python_m(
    monkeypatch, tmp_path
):
    import sys
    from types import SimpleNamespace

    from avo.adapters.base import JobRequest
    from avo.adapters.transcribe.faster_whisper import FasterWhisperAdapter
    from avo.engine_cli import _MODULES

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    calls = []

    def invoke(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr("avo.adapters.transcribe.faster_whisper.subprocess.run", invoke)
    result = FasterWhisperAdapter().run(
        JobRequest(
            "transcribe",
            "local",
            [
                "--library-batch",
                str(tmp_path),
                "--provider",
                "example",
                "--operation",
                "a" * 32,
            ],
        )
    )
    assert result.exit_code == 0 and "-m" not in calls[0]
    assert calls[0][1] == "library-worker"
    assert _MODULES["library-worker"] == "avo.library.batch"
    assert _MODULES["run_job"] == "avo.adapters.run_job"


def test_spec_cpu_only_ctranslate2() -> None:
    assert '_collect("ctranslate2")' in SPEC or 'collect_all("ctranslate2")' in SPEC
    assert (
        '_collect("faster_whisper")' in SPEC or 'collect_all("faster_whisper")' in SPEC
    )
    assert "matplotlib" in SPEC
    assert any(tok in SPEC for tok in ("cublas", "cudart", "cuda"))
    assert "__main__.py" in SPEC


def test_spec_does_not_collect_mcp_cli() -> None:
    assert '_collect("mcp")' not in SPEC
    assert "collect_all" in SPEC
    assert not any(
        line.strip()
        and not line.lstrip().startswith("#")
        and 'collect_all("mcp")' in line
        for line in SPEC.splitlines()
    )
    assert "mcp.cli" in SPEC
    assert "typer" in SPEC


def test_engine_binary_workflow_attaches_on_dispatch_not_only_release_event() -> None:
    """GITHUB_TOKEN-created releases do not fire on: release; attach via dispatch."""
    wf = (ROOT / ".github" / "workflows" / "engine-binary.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in wf
    assert "attach_tag:" in wf
    assert "github.event_name == 'release'" in wf
    assert "inputs.attach_tag" in wf
    assert "github.event.inputs.attach_tag" in wf
    assert "gh release upload" in wf
    assert "gh release edit" in wf
    assert "--draft=false" in wf


def test_build_scripts_zip_names_and_smoke() -> None:
    for text in (SH, PS1):
        assert (
            "avo-${VERSION}-${PLATFORM}.zip" in text or "avo-$Version-$Platform" in text
        )
        assert "version" in text
        assert "--help" in text
        assert "pip install avo" not in text
        assert "PyInstaller" in text
        assert "onefile" not in text.lower() or "Not onefile" in text
    assert "linux-x64" in SH
    assert "macos-arm64" in SH
    assert "windows-x64" in PS1
    assert "\u2014" not in PS1
    assert "\u2013" not in PS1


def _packaging_calls() -> set[tuple[str, str]]:
    import ast

    return {
        (node.func.id, node.args[0].value)
        for node in ast.walk(ast.parse(SPEC))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def test_code_drawn_extra_pins_independent_capture_dependency() -> None:
    import tomllib

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    capture = metadata["project"]["optional-dependencies"]["code-drawn"]
    assert capture == ["playwright==1.64.1"]
    package_data = metadata["tool"]["setuptools"]["package-data"]
    assert package_data.get("avo.templates.code_drawn")


def test_frozen_engine_collects_capture_driver_metadata_and_template_resources() -> (
    None
):
    calls = _packaging_calls()
    assert calls & {("_collect", "playwright"), ("collect_all", "playwright")}
    assert ("copy_metadata", "playwright") in calls
    assert ("collect_data_files", "avo.templates.code_drawn") in calls
    assert ("collect_all", "hyperframes") not in calls


def test_both_frozen_builds_install_capture_extra_without_bundling_browsers() -> None:
    import re

    for build in (SH, PS1):
        extras = {
            item.strip()
            for group in re.findall(r"\.\[([^\]]+)\]", build)
            for item in group.split(",")
        }
        assert {"mcp", "code-drawn"}.issubset(extras)
        assert "PLAYWRIGHT_BROWSERS_PATH=0" not in build
        assert 'PLAYWRIGHT_BROWSERS_PATH="0"' not in build


def test_zip_smoke_exercises_capture_with_only_extracted_native_commands() -> None:
    import re

    smoke = (ROOT / "scripts/ci/engine-binary-smoke.sh").read_text(encoding="utf-8")
    assert "tempfile.mkdtemp" in smoke, "Smoke must start in a fresh OS temp workspace."
    assert re.search(r"(?m)^unset AVO_ROOT PYTHONPATH", smoke)
    assert not re.search(r"(?m)^\s*rm\s+-rf\b", smoke)
    for operation in (
        "runtime-install",
        "code-drawn-scaffold",
        "code-drawn-check",
        "code-drawn-render",
    ):
        assert re.search(rf'(?m)^\s*"\$LAUNCHER" cli animation {operation}\b', smoke), (
            operation
        )
    assert "import avo" not in smoke
    assert "from avo" not in smoke
    assert "PLAYWRIGHT_BROWSERS_PATH" in smoke
    assert "AVO_REQUIRE_CODE_DRAWN_RUNTIME" in smoke


def test_binary_capture_lane_provisions_encoder_and_only_browser_system_dependencies() -> (
    None
):
    workflow = (ROOT / ".github/workflows/engine-binary.yml").read_text(
        encoding="utf-8"
    )
    for install in ("apt-get install", "brew install ffmpeg", "choco install ffmpeg"):
        assert install in workflow, install
    assert "python -m playwright install-deps chromium" in workflow
    assert "python -m playwright install --with-deps" not in workflow
    assert "python -m playwright install --no-shell" not in workflow
    assert "steps.code-drawn.outputs.enabled" in workflow


def test_zip_smoke_harness_override_precedes_automatic_python_discovery() -> None:
    smoke = (ROOT / "scripts/ci/engine-binary-smoke.sh").read_text(encoding="utf-8")
    override = smoke.index('if [[ -n "${AVO_SMOKE_PYTHON:-}" ]]')
    assert override < smoke.index("command -v python3")
    assert 'PYTHON="$AVO_SMOKE_PYTHON"' in smoke
    assert "sys.version_info >= (3, 11)" in smoke
    assert "Path(sys.argv[1]).is_absolute()" in smoke


def test_extracted_capture_smoke_covers_all_three_routes():
    smoke = (ROOT / "scripts/ci/engine-binary-smoke.sh").read_text(encoding="utf-8")
    assert "for route in svg brush" in smoke
    assert "--brush --json" in smoke
    assert "route-output-probe" in smoke


def test_both_builds_ship_only_the_canonical_provider_schema_beside_launcher():
    assert '"$ONEDIR/providers/avo.provider.schema.json"' in SH
    assert '"$ROOT/providers/avo.provider.schema.json"' in SH
    assert 'Join-Path $Onedir "providers"' in PS1
    assert 'Join-Path $Root "providers\\avo.provider.schema.json"' in PS1
    assert "Copy-Item -LiteralPath" in PS1
    for build in (SH, PS1):
        assert "avo.provider.schema.json" in build
        assert "providers/*" not in build
        assert "providers\\*" not in build
    assert SH.index('"$ONEDIR/providers/avo.provider.schema.json"') < SH.index(
        "shutil.make_archive"
    )
    assert PS1.index('Join-Path $Onedir "providers"') < PS1.index("shutil.make_archive")
