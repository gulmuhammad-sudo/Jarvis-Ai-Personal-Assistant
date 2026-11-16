"""GPU usage, measured the way Task Manager does it (Windows performance counters).

GPU % = the busiest engine type (3D, video decode, compute...) summed over all apps.
Memory = dedicated + shared GPU memory in use. Works for AMD, Intel and NVIDIA alike.
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict

try:
    import win32pdh
except ImportError:          # pywin32 missing or not Windows: no GPU gauge
    win32pdh = None

ENGINES = r"\GPU Engine(*)\Utilization Percentage"
MEMORY = (r"\GPU Adapter Memory(*)\Dedicated Usage", r"\GPU Adapter Memory(*)\Shared Usage")


class GpuMonitor:
    def __init__(self) -> None:
        self.percent: float | None = None      # 0-100, None = unknown
        self.engine = ""                        # busiest engine type, e.g. "3D"
        self.mem_mb: int | None = None
        self.name = ""

    def start(self) -> None:
        if win32pdh:
            threading.Thread(target=self._run, name="jarvis-gpu", daemon=True).start()

    def _run(self) -> None:
        self.name = _gpu_name()
        while True:
            try:
                self._sample_for(15)                # apps come and go: re-list the counters every 15 s
            except Exception as e:
                print(f"[gpu] {type(e).__name__}: {e}")
                self.percent = None
                time.sleep(30)

    def _sample_for(self, seconds: float) -> None:
        q = win32pdh.OpenQuery()
        try:
            eng = []
            for path in win32pdh.ExpandCounterPath(ENGINES):
                m = re.search(r"luid_(\w+?)_phys.*engtype_([^)]*)", path)
                eng.append(((m.group(1), m.group(2)) if m else ("?", "?"), win32pdh.AddCounter(q, path)))
            mem = [win32pdh.AddCounter(q, p) for pattern in MEMORY for p in win32pdh.ExpandCounterPath(pattern)]
            win32pdh.CollectQueryData(q)
            end = time.time() + seconds
            while time.time() < end:
                time.sleep(2)
                win32pdh.CollectQueryData(q)
                busy: dict[tuple, float] = defaultdict(float)
                for key, h in eng:
                    try:
                        busy[key] += win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_DOUBLE)[1]
                    except Exception:             # that app closed
                        pass
                if busy:
                    key, top = max(busy.items(), key=lambda kv: kv[1])
                    self.percent, self.engine = round(min(top, 100.0), 1), key[1]
                else:
                    self.percent, self.engine = 0.0, ""
                used = 0
                for h in mem:
                    try:
                        used += win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_LARGE)[1]
                    except Exception:
                        pass
                self.mem_mb = used // 2 ** 20 if mem else None
        finally:
            win32pdh.CloseQuery(q)

    def status(self) -> dict:
        return {"gpu": self.percent, "gpu_engine": self.engine, "gpu_mem_mb": self.mem_mb, "gpu_name": self.name}


_monitor: GpuMonitor | None = None
_monitor_lock = threading.Lock()


def monitor() -> GpuMonitor:
    """The one GPU monitor (started the first time it is asked for)."""
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = GpuMonitor()
            _monitor.start()
        return _monitor


def _gpu_name() -> str:
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Basic|Remote|Virtual' }"
                              " | Select-Object -First 1).Name"],
                             capture_output=True, text=True, timeout=15, creationflags=0x08000000).stdout.strip()
        return out.replace("(TM)", "").replace("(R)", "").strip()
    except Exception:
        return ""
