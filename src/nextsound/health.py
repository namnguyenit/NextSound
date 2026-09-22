from __future__ import annotations

import ctypes
import errno
import os
import tempfile
from pathlib import Path


def inotify_watch_available(
    path: str | Path = "/tmp", required_watches: int = 64
) -> tuple[bool, str]:
    """Probe whether the current user has enough watches for a safe restart."""
    if required_watches < 1:
        raise ValueError("required_watches must be positive")

    libc = ctypes.CDLL(None, use_errno=True)
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    libc.inotify_add_watch.restype = ctypes.c_int

    try:
        probe_directory = tempfile.TemporaryDirectory(
            prefix="nextsound-inotify-", dir=os.fspath(path)
        )
    except OSError as error:
        return False, str(error)

    fd = libc.inotify_init1(getattr(os, "O_CLOEXEC", 0))
    if fd < 0:
        error_number = ctypes.get_errno()
        probe_directory.cleanup()
        return False, os.strerror(error_number)

    try:
        for index in range(required_watches):
            target = Path(probe_directory.name) / str(index)
            try:
                target.touch()
            except OSError as error:
                return False, str(error)
            watch = libc.inotify_add_watch(fd, os.fsencode(target), 0x00000004)
            if watch >= 0:
                continue
            error_number = ctypes.get_errno()
            if error_number == errno.ENOSPC:
                return False, "không đủ inotify watches dự phòng"
            return False, os.strerror(error_number)
        return True, f"còn ít nhất {required_watches} watches dự phòng"
    finally:
        os.close(fd)
        probe_directory.cleanup()
