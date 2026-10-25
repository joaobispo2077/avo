"""Schema lookup keeps checkout behavior and supports installed data files."""

from avo import paths


def setup_paths(tmp_path, monkeypatch):
    root = tmp_path / "empty-checkout"
    root.mkdir()
    prefix = tmp_path / "installed"
    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setattr(paths.sys, "prefix", str(prefix))
    return root, prefix


def test_installed_schema_fallback_without_checkout(tmp_path, monkeypatch):
    root, prefix = setup_paths(tmp_path, monkeypatch)
    directory = prefix / "share/avo/schemas"
    directory.mkdir(parents=True)
    schema = directory / "avo.direction.schema.json"
    schema.write_text("{}")
    assert paths.schema_path(schema.name) == schema
    assert paths.schemas_dir() == directory
    assert not (root / "schemas").exists()


def test_checkout_schema_keeps_precedence(tmp_path, monkeypatch):
    root, prefix = setup_paths(tmp_path, monkeypatch)
    for directory in (root / "schemas", prefix / "share/avo/schemas"):
        directory.mkdir(parents=True)
        (directory / "avo.direction.schema.json").write_text("{}")
    assert (
        paths.schema_path("avo.direction.schema.json")
        == root / "schemas/avo.direction.schema.json"
    )
    assert paths.schemas_dir() == root / "schemas"


def test_target_installed_schema_beside_package(tmp_path, monkeypatch):
    _, _ = setup_paths(tmp_path, monkeypatch)
    package = tmp_path / "target/avo/paths.py"
    monkeypatch.setattr(paths, "__file__", str(package))
    directory = package.parent.parent / "share/avo/schemas"
    directory.mkdir(parents=True)
    schema = directory / "avo.briefstart.schema.json"
    schema.write_text("{}")
    assert paths.schema_path(schema.name) == schema
    assert paths.schemas_dir() == directory


def test_absent_installed_schemas_keep_legacy_missing_path(tmp_path, monkeypatch):
    root, _ = setup_paths(tmp_path, monkeypatch)
    assert (
        paths.schema_path("not-installed.schema.json")
        == root / "not-installed.schema.json"
    )
