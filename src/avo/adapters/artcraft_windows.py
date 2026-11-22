"""Read installed ArtCraft application versions without launching the app."""

import sys

from avo.artcraft import ArtCraftError


def windows_application_release(path, product):
    """Read the Windows version resource without starting the desktop application."""
    if sys.platform != "win32":
        raise ArtCraftError(
            f"{product} release inspection requires Windows", code="ARTCRAFT_NOT_READY"
        )
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version", winmode=0x800)
    size_of = version.GetFileVersionInfoSizeW
    size_of.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    size_of.restype = wintypes.DWORD
    read = version.GetFileVersionInfoW
    read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    read.restype = wintypes.BOOL
    query = version.VerQueryValueW
    query.argtypes = [
        wintypes.LPCVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.UINT),
    ]
    query.restype = wintypes.BOOL
    size = size_of(str(path), None)
    if not 0 < size <= 1024 * 1024:
        raise ArtCraftError(
            f"{product} has no bounded Windows version record",
            code="ARTCRAFT_NOT_READY",
        )
    buffer = ctypes.create_string_buffer(size)
    pointer = wintypes.LPVOID()
    length = wintypes.UINT()
    if not read(str(path), 0, size, buffer) or not query(
        buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
    ):
        raise ArtCraftError(
            f"{product} Windows version record could not be read",
            code="ARTCRAFT_NOT_READY",
        )
    if length.value < 6 * ctypes.sizeof(wintypes.DWORD):
        raise ArtCraftError(
            f"{product} Windows version record is incomplete", code="ARTCRAFT_NOT_READY"
        )
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if words[0] != 0xFEEF04BD:
        raise ArtCraftError(
            f"{product} Windows version record is invalid", code="ARTCRAFT_NOT_READY"
        )
    major, minor = divmod(words[4], 65536)
    release, build = divmod(words[5], 65536)
    fields = (major, minor, release, build) if build else (major, minor, release)
    return ".".join(map(str, fields))
