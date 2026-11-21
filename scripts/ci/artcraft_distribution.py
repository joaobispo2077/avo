"""Identify native vendor payloads in the AVO release files."""

from pathlib import PurePosixPath

_NATIVE_SUFFIXES = {
    ".appimage",
    ".dll",
    ".dmg",
    ".dylib",
    ".exe",
    ".msi",
    ".pkg",
    ".so",
    ".zip",
}


def native_artcraft_paths(paths, apps):
    """Match standalone app or CLI names, macOS bundles and named installers."""
    apps = set(apps)
    bundles = {app + ".app" for app in apps}
    standalone = apps | {app + "-cli" for app in apps}
    prefixes = tuple(app + "-" for app in apps)
    matched = []
    for entry in paths:
        path = PurePosixPath(entry.casefold().replace("\\", "/"))
        named_binary = path.suffix in _NATIVE_SUFFIXES and (
            path.stem in standalone or path.stem.startswith(prefixes)
        )
        if bundles.intersection(path.parts) or path.name in standalone or named_binary:
            matched.append(entry)
    return matched
