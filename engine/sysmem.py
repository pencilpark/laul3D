"""Physical memory available now, for the choices that depend on it (SIFT threads, Max resolution, 8192 textures).

Standard library only: Blender's Python imports it too.
"""
import os
import re
import subprocess
import sys


def free_memory():
    """Bytes of physical memory available now, or None when unknown. LOWPOLY_FREE_MEMORY_GB stands in for the
    measure: to try what an 8 GB computer would get, or to leave memory to other work."""
    forced = os.environ.get("LOWPOLY_FREE_MEMORY_GB")
    if forced:
        try:
            return float(forced) * 2 ** 30
        except ValueError:
            pass
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                           [(n, ctypes.c_ulonglong) for n in ("total", "avail", "page_total", "page_avail",
                                                              "virt_total", "virt_avail", "ext_avail")]
            s = Status()
            s.length = ctypes.sizeof(s)
            return s.avail if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)) else None
        if sys.platform == "darwin":
            # what macOS hands out without swapping: free, speculative and inactive pages (psutil counts the same)
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+) bytes", out).group(1))
            pages = re.findall(r"Pages (?:free|speculative|inactive):\s+(\d+)", out)
            return page * sum(map(int, pages)) if pages else None
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError, subprocess.SubprocessError):
        return None
