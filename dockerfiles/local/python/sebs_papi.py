"""Hardware counters with PAPI in local function containers.

A ctypes binding to libsebs_papi.so (dockerfiles/local/python/papi/sebs_papi.c),
built against the PAPI library of the run image.

    counters = PAPI(["PAPI_TOT_INS", "PAPI_TOT_CYC"])
    counters.overflow("PAPI_TOT_INS", 1_000_000)  # optional: sample all events
    counters.start()
    ...
    totals = counters.stop()          # {"PAPI_TOT_INS": ..., "PAPI_TOT_CYC": ...}
    rows = counters.samples()         # [(timestamp_us, [ins, cyc]), ...]
    counters.finish()

Requires access to performance counters: SeBS starts local containers as privileged,
and the host's kernel.perf_event_paranoid must allow user-space counting (2 or lower).
"""

import ctypes
from typing import Dict, Iterable, List, Optional, Tuple

LIBRARY = "libsebs_papi.so"


class PAPIError(RuntimeError):
    pass


def _load(path: str) -> ctypes.CDLL:
    lib = ctypes.CDLL(path)
    lib.sebs_papi_strerror.restype = ctypes.c_char_p
    lib.sebs_papi_strerror.argtypes = [ctypes.c_int]
    lib.sebs_papi_add_event.argtypes = [ctypes.c_char_p]
    lib.sebs_papi_overflow.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_longlong]
    lib.sebs_papi_stop.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
    lib.sebs_papi_num_samples.restype = ctypes.c_longlong
    lib.sebs_papi_num_dropped.restype = ctypes.c_longlong
    lib.sebs_papi_take_samples.restype = ctypes.c_longlong
    lib.sebs_papi_take_samples.argtypes = [ctypes.POINTER(ctypes.c_longlong), ctypes.c_longlong]
    return lib


class PAPI:
    """One PAPI event set; only one may exist per process."""

    def __init__(
        self, events: Iterable[str], skip_unavailable: bool = False, library: str = LIBRARY
    ):
        """Adds the events by name (PAPI presets or native events).

        With skip_unavailable, events the CPU doesn't support are left out and
        listed in `unavailable`; otherwise the first one raises PAPIError.
        """
        self._lib = _load(library)
        self._check(self._lib.sebs_papi_init(), "initializing PAPI")
        self.events: List[str] = []
        self.unavailable: Dict[str, str] = {}
        for name in events:
            ret = self._lib.sebs_papi_add_event(name.encode())
            if ret == 0:
                self.events.append(name)
            elif skip_unavailable:
                self.unavailable[name] = self._error(ret)
            else:
                self.finish()
                raise PAPIError(f"adding event {name}: {self._error(ret)}")

    def _error(self, code: int) -> str:
        msg = self._lib.sebs_papi_strerror(code)
        return f"{msg.decode() if msg else 'unknown error'} ({code})"

    def _check(self, code: int, what: str) -> None:
        if code != 0:
            raise PAPIError(f"{what}: {self._error(code)}")

    def overflow(self, event: str, threshold: int, max_samples: int = 1_000_000) -> None:
        """Sample all events every `threshold` occurrences of `event` (must be added)."""
        self._check(
            self._lib.sebs_papi_overflow(event.encode(), int(threshold), int(max_samples)),
            f"overflow sampling on {event}",
        )

    def start(self) -> None:
        self._check(self._lib.sebs_papi_start(), "starting counters")

    def stop(self) -> Dict[str, int]:
        """Stops counting; returns the total count of each event."""
        values = (ctypes.c_longlong * max(len(self.events), 1))()
        self._check(self._lib.sebs_papi_stop(values), "stopping counters")
        return dict(zip(self.events, values))

    @property
    def dropped(self) -> int:
        """Samples lost because the buffer was full (raise max_samples)."""
        return self._lib.sebs_papi_num_dropped()

    def samples(self) -> List[Tuple[int, List[int]]]:
        """Takes the overflow samples: (timestamp in microseconds, event values) each."""
        count = self._lib.sebs_papi_num_samples()
        width = len(self.events) + 1
        buffer = (ctypes.c_longlong * (count * width or 1))()
        rows = self._lib.sebs_papi_take_samples(buffer, count)
        samples = []
        for row in range(rows):
            first = row * width + 1
            last = (row + 1) * width
            samples.append((buffer[first - 1], buffer[first:last]))
        return samples

    def finish(self) -> None:
        self._lib.sebs_papi_finish()


def available(library: str = LIBRARY) -> Optional[str]:
    """None if PAPI can count in this container, otherwise the reason it can't."""
    try:
        counters = PAPI(["PAPI_TOT_INS"], library=library)
    except (OSError, PAPIError) as e:
        return str(e)
    try:
        counters.start()
        counters.stop()
    except PAPIError as e:
        return str(e)
    finally:
        counters.finish()
    return None
