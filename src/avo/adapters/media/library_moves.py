"""Handle-pinned, no-replace raw moves on tested local Windows NTFS storage.

Other platforms/storage refuse apply. Metadata publication may use replace;
raw media never does. The caller owns approval, journaling and reconciliation.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

from avo.library.rules import LibraryError, reject, safe_path

_DIRECTORY = 0x10
_REPARSE = 0x400
_BACKUP_SEMANTICS = 0x02000000
_OPEN_REPARSE = 0x00200000
_READ = 0x80000000
_DELETE = 0x00010000
_LOCK_FIELDS = ("sha256", "sizeBytes", "device", "fileId", "mtimeNs", "ctimeNs")


class _FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("creation", wintypes.FILETIME),
        ("access", wintypes.FILETIME),
        ("write", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("sizeHigh", wintypes.DWORD),
        ("sizeLow", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("indexHigh", wintypes.DWORD),
        ("indexLow", wintypes.DWORD),
    ]


class _RenameInfo(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD),
        ("root", wintypes.HANDLE),
        ("nameLength", wintypes.DWORD),
        ("name", wintypes.WCHAR * 1),
    ]


@lru_cache(maxsize=1)
def _api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateFileW": (
            [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ],
            wintypes.HANDLE,
        ),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetFileInformationByHandle": (
            [wintypes.HANDLE, ctypes.POINTER(_FileInfo)],
            wintypes.BOOL,
        ),
        "SetFileInformationByHandle": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "GetFinalPathNameByHandleW": (
            [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD],
            wintypes.DWORD,
        ),
        "GetVolumePathNameW": (
            [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "GetDriveTypeW": ([wintypes.LPCWSTR], wintypes.UINT),
        "GetVolumeInformationW": (
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPWSTR,
                wintypes.DWORD,
            ],
            wintypes.BOOL,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = arguments
        function.restype = result
    return api


def capability(root) -> dict:
    """Report availability without writing files or attempting a move."""
    unavailable = {"available": False, "platform": sys.platform, "filesystem": None}
    if sys.platform != "win32":
        return {**unavailable, "reason": "Native moves require Windows local NTFS"}
    if str(root).startswith(("\\\\", "//")):
        return {
            **unavailable,
            "reason": "Network roots are unsupported for native moves",
        }
    root = Path(root).absolute()
    if not root.is_dir():
        return {
            **unavailable,
            "reason": "Native move root must be an existing directory",
        }
    volume = ctypes.create_unicode_buffer(32768)
    filesystem = ctypes.create_unicode_buffer(32)
    api = _api()
    if not api.GetVolumePathNameW(str(root), volume, len(volume)):
        return {**unavailable, "reason": "Cannot verify the root volume"}
    if api.GetDriveTypeW(volume.value) != 3:
        return {**unavailable, "reason": "Native moves require a fixed local volume"}
    if not api.GetVolumeInformationW(
        volume.value, None, 0, None, None, None, filesystem, len(filesystem)
    ):
        return {**unavailable, "reason": "Cannot verify the root filesystem"}
    if filesystem.value.upper() != "NTFS":
        return {
            **unavailable,
            "filesystem": filesystem.value,
            "reason": "Native moves are tested only on NTFS",
        }
    return {
        "available": True,
        "platform": sys.platform,
        "filesystem": "NTFS",
        "volume": volume.value,
        "reason": "Local NTFS handle rename available",
    }


def _file_info(handle):
    information = _FileInfo()
    if not _api().GetFileInformationByHandle(handle, ctypes.byref(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    if information.attributes & _REPARSE:
        reject("LIB_ROOT_UNSAFE", "Native move paths cannot contain reparse points")
    return information


def _open(path, *, source=False):
    handle = _api().CreateFileW(
        "\\\\?\\" + str(path),
        _READ | _DELETE if source else 0x80 | 0x20,
        1 if source else 3,
        None,
        3,
        _OPEN_REPARSE | _BACKUP_SEMANTICS,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


@contextmanager
def _directory(path):
    handle = _open(path)
    try:
        information = _file_info(handle)
        if not information.attributes & _DIRECTORY:
            reject("LIB_ROOT_UNSAFE", "Native move ancestor is not a directory")
        yield handle, information.volume
    finally:
        _api().CloseHandle(handle)


def _hold_parents(stack, parent, *, create=False):
    """Pin every ancestor, including those above the selected root."""
    result = None
    for path in [*reversed(parent.parents), parent]:
        if create:
            path.mkdir(exist_ok=True)
        result = stack.enter_context(_directory(path))
    return result


@contextmanager
def _source_stream(path):
    import msvcrt

    handle = _open(path, source=True)
    try:
        information = _file_info(handle)
        if information.attributes & _DIRECTORY or information.links != 1:
            reject("LIB_ROOT_UNSAFE", "Only single-link regular source files may move")
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _api().CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "rb") as stream:
        yield stream, handle, information.volume


def _stream_lock(stream):
    before = os.fstat(stream.fileno())
    stream.seek(0)
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    after = os.fstat(stream.fileno())
    fields = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_dev", "st_ino", "st_nlink")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        reject(
            "LIB_SOURCE_CHANGED", "Source changed during native verification", "stale"
        )
    if after.st_nlink != 1:
        reject("LIB_ROOT_UNSAFE", "Native source acquired an unexpected hard link")
    return {
        "sha256": digest.hexdigest(),
        "sizeBytes": after.st_size,
        "device": after.st_dev,
        "fileId": after.st_ino,
        "mtimeNs": after.st_mtime_ns,
        "ctimeNs": after.st_ctime_ns,
    }


def _same_lock(actual, expected):
    if any(actual[field] != expected[field] for field in _LOCK_FIELDS):
        reject(
            "LIB_SOURCE_CHANGED", "Native source differs from approved lock", "stale"
        )


def _rename_handle(handle, target_parent, name):
    """FileRenameInfo with ReplaceIfExists=false and every ancestor pinned."""
    parent = ctypes.create_unicode_buffer(32768)
    length = _api().GetFinalPathNameByHandleW(target_parent, parent, len(parent), 0)
    if not length or length >= len(parent):
        raise ctypes.WinError(ctypes.get_last_error())
    # Tested Win32 rejects a non-null RootDirectory with error 87. The absolute
    # name is obtained from the pinned handle; all ancestors deny delete sharing.
    encoded = (parent.value.rstrip("\\") + "\\" + name).encode("utf-16-le")
    size = ctypes.sizeof(_RenameInfo) + len(encoded) + ctypes.sizeof(wintypes.WCHAR)
    buffer = ctypes.create_string_buffer(size)
    information = _RenameInfo(0, None, len(encoded))
    ctypes.memmove(buffer, ctypes.byref(information), ctypes.sizeof(information))
    ctypes.memmove(
        ctypes.addressof(buffer) + _RenameInfo.name.offset, encoded, len(encoded)
    )
    if not _api().SetFileInformationByHandle(handle, 3, buffer, size):
        raise ctypes.WinError(ctypes.get_last_error())


def _move_error(error, *, moved):
    winerror = getattr(error, "winerror", None)
    if moved:
        return LibraryError(
            "LIB_RECONCILIATION_REQUIRED",
            "Move needs outcome reconciliation",
            status="conflict",
        )
    if winerror in {80, 183}:
        return LibraryError(
            "LIB_DESTINATION_EXISTS", "Destination already exists", status="conflict"
        )
    if winerror in {32, 33}:
        return LibraryError(
            "LIB_RESOURCE_BUSY",
            "A move path is open for conflicting access",
            status="conflict",
        )
    return LibraryError(
        "LIB_MOVE_UNSUPPORTED",
        "Native move could not be safely completed",
        status="unavailable",
    )


def move_no_replace(root, source_relative, destination_relative, expected_lock) -> dict:
    """Move one approved source; verify bytes and file ID through its held handle."""
    support = capability(root)
    if not support["available"]:
        reject("LIB_MOVE_UNSUPPORTED", support["reason"], "unavailable")
    root = Path(root).absolute()
    source = safe_path(root, source_relative)
    destination = safe_path(root, destination_relative)
    if (
        not isinstance(expected_lock, dict)
        or not set(_LOCK_FIELDS) <= expected_lock.keys()
    ):
        reject("LIB_INVALID_REQUEST", "A complete source lock is required")
    if str(source).casefold() == str(destination).casefold():
        reject("LIB_ROOT_UNSAFE", "Same-path and case-only moves are unsupported")
    moved = False
    try:
        with ExitStack() as stack:
            root_handle, root_volume = _hold_parents(stack, root)
            del root_handle
            _hold_parents(stack, source.parent)
            target_handle, target_volume = _hold_parents(
                stack, destination.parent, create=True
            )
            safe_path(root, source_relative)
            safe_path(root, destination_relative)
            if destination.exists():
                reject(
                    "LIB_DESTINATION_EXISTS", "Destination already exists", "conflict"
                )
            stream, source_handle, source_volume = stack.enter_context(
                _source_stream(source)
            )
            if source_volume != root_volume or target_volume != root_volume:
                reject("LIB_ROOT_UNSAFE", "Native move cannot cross volumes")
            _same_lock(_stream_lock(stream), expected_lock)
            _rename_handle(source_handle, target_handle, destination.name)
            moved = True
            verified = _stream_lock(stream)
            _same_lock(verified, expected_lock)
            return verified
    except OSError as error:
        raise _move_error(error, moved=moved) from error
