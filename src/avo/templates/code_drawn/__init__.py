"""Framework-independent drawing starters and immutable optional brush pins."""

from __future__ import annotations

from pathlib import Path

BRUSH_VERSION = "2.2.3"
BRUSH_SHA256 = "952c1853b7699e6052b9f53d917cd09ea7c35f79d9f5b25e8665a937c618caae"
BRUSH_LICENSE_SHA256 = (
    "cabbece1a276329fa28ab40f1c99af3af2b7852a329551a9a485b2199616583a"
)


def brush_cache_paths(home: Path | None = None) -> tuple[Path, Path]:
    """Locate provisioned bytes; this function never reads or provisions them."""
    base = Path(home) if home is not None else Path.home()
    directory = base / ".avo" / "runtime" / "code-drawn" / "brush" / BRUSH_VERSION
    return directory / "brush.js", directory / "LICENSE.md"
