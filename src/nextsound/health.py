from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path


def inotify_watch_available(path: str | Path = "/tmp") -> tuple[bool, str]:
    """Probe whether the current user can allocate one inotify watch."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    libc.inotify_add_watch.restype = ctypes.c_int

    fd = libc.inotify_init1(getattr(os, "O_CLOEXEC", 0))
    if fd < 0:
        error_number = ctypes.get_errno()
        return False, os.strerror(error_number)

    try:
        watch = libc.inotify_add_watch(fd, os.fsencode(path), 0x00000004)
        if watch >= 0:
            return True, "còn dung lượng"
        error_number = ctypes.get_errno()
        if error_number == errno.ENOSPC:
            return False, "đã dùng hết inotify watches"
        return False, os.strerror(error_number)
    finally:
        os.close(fd)
