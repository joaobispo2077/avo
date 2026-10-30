"""Strict library records, bounded imports and contained source paths."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator

from avo.paths import schema_path


class LibraryError(ValueError):
    """A failed library trust or capability boundary."""

    def __init__(self, code, message=None, *, status="invalid-request"):
        self.code = code
        self.status = status
        super().__init__(message or code)


def reject(code, message, status="invalid-request"):
    raise LibraryError(code, message, status=status)


def no_constant(value):
    raise ValueError(f"Non-finite number: {value}")


def _reader(path):
    if os.name != "nt":
        return Path(path).open("rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(str(Path(path).absolute()), 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "rb")


def read_request(path, expected_hash=None, *, limit=2 * 1024 * 1024):
    try:
        with _reader(path) as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                reject("LIB_INPUT_TOO_LARGE", "Expected a bounded regular JSON file")
            raw = stream.read(before.st_size + 1)
            if os.fstat(stream.fileno()).st_size != before.st_size:
                reject("LIB_SOURCE_CHANGED", "Input changed while reading", "stale")
        if len(raw) > limit:
            reject("LIB_INPUT_TOO_LARGE", "Input exceeds its declared byte limit")
        if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
            reject("LIB_SOURCE_CHANGED", "Request differs from reviewed bytes", "stale")
        value = json.loads(raw, parse_constant=no_constant)
        if not isinstance(value, dict):
            reject("LIB_INVALID_REQUEST", "Expected a JSON object")
        return value
    except (OSError, ValueError) as exc:
        if isinstance(exc, LibraryError):
            raise
        raise LibraryError(
            "LIB_INVALID_REQUEST", "Cannot read bounded JSON input"
        ) from exc


@lru_cache(maxsize=32)
def validator(kind):
    schema = json.loads(
        schema_path("avo.library.schema.json").read_text(encoding="utf-8")
    )
    if kind not in schema["$defs"]:
        reject("LIB_INVALID_REQUEST", "Unknown library document kind")
    return Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]})


def validate(kind, value):
    errors = list(validator(kind).iter_errors(value))
    if errors:
        reject("LIB_INVALID_REQUEST", f"Invalid {kind}: {errors[0].message}")
    # jsonschema's number type alone does not reject non-finite Python floats.
    encoded = json.dumps(value, allow_nan=False)
    if len(encoded.encode("utf-8")) > 32 * 1024 * 1024:
        reject("LIB_INPUT_TOO_LARGE", "Document exceeds 32 MiB")
    return value


def is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def _relative_parts(relative):
    if not isinstance(relative, str) or not relative:
        reject("LIB_ROOT_UNSAFE", "A nonempty relative path is required")
    parts = PurePosixPath(relative).parts
    bad = (
        "\\" in relative
        or ":" in relative
        or PurePosixPath(relative).is_absolute()
        or PureWindowsPath(relative).drive
        or ".." in parts
        or not parts
    )
    if bad:
        reject("LIB_ROOT_UNSAFE", "Path leaves the selected root")
    return parts


def _component(part):
    if part.endswith((".", " ")) or re.search(r'[<>"|?*\x00-\x1f]', part):
        reject("LIB_ROOT_UNSAFE", "Unsafe filename component")
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
        reject("LIB_ROOT_UNSAFE", "Reserved filename component")


def safe_path(root, relative):
    parts = _relative_parts(relative)
    for part in parts:
        _component(part)
    root = Path(root).absolute()
    _root_ancestors(root)
    current = root
    for item in [None, *parts]:
        if item is not None:
            current = current / item
        if (current.exists() or current.is_symlink()) and is_link(current):
            reject("LIB_ROOT_UNSAFE", "Links and reparse paths are unsupported")
    if not current.resolve().is_relative_to(root.resolve()):
        reject("LIB_ROOT_UNSAFE", "Resolved path leaves selected root")
    return current


def _root_ancestors(root):
    for parent in root.parents:
        if parent.exists() and is_link(parent):
            reject("LIB_ROOT_UNSAFE", "Selected root has a linked ancestor")


def observation(path):
    info = path.stat(follow_symlinks=False)
    return {
        "sizeBytes": info.st_size,
        "mtimeNs": info.st_mtime_ns,
        "ctimeNs": info.st_ctime_ns,
        "device": info.st_dev,
        "fileId": info.st_ino,
    }


def source_lock(path):
    before = observation(path)
    if not path.is_file() or is_link(path) or path.stat().st_nlink != 1:
        reject("LIB_ROOT_UNSAFE", "Only unlinked regular source files are eligible")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    if observation(path) != before:
        reject("LIB_SOURCE_CHANGED", "Source changed while verifying", "stale")
    return {**before, "sha256": digest.hexdigest()}


def verify_source(path, expected):
    actual = source_lock(path)
    if any(
        actual[k] != expected[k] for k in ("sha256", "sizeBytes", "device", "fileId")
    ):
        reject("LIB_SOURCE_CHANGED", "Source identity differs from approval", "stale")
    return actual


def finite_seconds(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
