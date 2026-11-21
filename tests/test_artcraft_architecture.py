"""Keep ordinary AVO entry points independent of optional ArtCraft execution."""

import subprocess
import sys


def test_ordinary_cli_help_does_not_import_native_artcraft_adapters(tmp_path):
    startup = """
import sys
from avo.cli import main

try:
    main(["--help"])
except SystemExit as result:
    assert result.code == 0

assert not any(name.startswith("avo.adapters.artcraft") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", startup],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        timeout=12,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []
