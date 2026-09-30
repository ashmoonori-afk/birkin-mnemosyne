"""Cold-start probe, run in a fresh interpreter by bench_retrieval.cold_start:

    python _probe.py <engine> <vault> <query> [build]

Prints one JSON line: ``load_ms`` (library import + engine construction +
first query, timed after the stdlib imports; the parent adds the
process wall time) and ``peak_rss`` in bytes
(None only on platforms with neither psapi nor ``resource``). With ``build``
the engine first builds its index from the notes, so ``peak_rss`` is the
peak of bulk indexing in a process that holds nothing else."""

import json
import os
import sys
import time
from pathlib import Path

T0 = time.perf_counter()


def peak_rss_bytes() -> int | None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        handle = ctypes.WinDLL("kernel32").GetCurrentProcess()
        if not get_info(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return int(counters.PeakWorkingSetSize)
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def main() -> None:
    engine_name, vault, query = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    here = Path(__file__).resolve().parent
    sys.path[:0] = [str(here), str(here.parents[1])]
    from engines import ENGINES

    engine = ENGINES[engine_name](vault)
    if sys.argv[4:] == ["build"]:
        engine.build()
    engine.search(query, 10)
    load_ms = (time.perf_counter() - T0) * 1000.0
    print(json.dumps({"load_ms": load_ms, "peak_rss": peak_rss_bytes()}))


if __name__ == "__main__":
    main()
