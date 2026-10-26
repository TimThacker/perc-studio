"""Runs PSS/E cases: one worker process per case, each in a Windows Job Object
with a wall-clock timeout, several in parallel, with a content-addressed cache.

One process per case is deliberate: PSS/E 36.7 keeps model memory across
psseinit, and 35.6 aborts a session after about 190 cases (measured in
the PSS/E validation library, which is not published). A user DLL is native code that can hang
or crash, so every process is killed with its whole tree when it overruns.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.resources import resource_path

from .logparse import parse_log

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WORKER_NAME = "psse_worker.py"
READER_NAME = "outx.py"  # the channel-file reader the worker imports; it travels with the worker
DEFAULT_DELT = 1.0 / 240.0
DEFAULT_FREQ_FILTER = 0.033333
MIN_TIMEOUT_S = 60.0
TIMEOUT_PER_SIM_SECOND = 20.0
MEMORY_LIMIT_BYTES = 4 * 1024**3
LICENSE_RETRIES = 3
PUBLISH_RETRIES = 8
PUBLISH_WAIT_S = 0.25


def worker_source() -> Path:
    return resource_path("src", "psse_worker", WORKER_NAME)


def reader_source() -> Path:
    return resource_path("src", "blackbox", READER_NAME)


def worker_hash() -> str:
    """Cache key part: a change to the worker or to the reader it uses invalidates cached cases."""
    return hashlib.sha256(worker_source().read_bytes() + reader_source().read_bytes()).hexdigest()


def stage_worker(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / WORKER_NAME
    shutil.copyfile(worker_source(), target)
    shutil.copyfile(reader_source(), folder / READER_NAME)
    return target


# --- one process ---------------------------------------------------------------------------------------------------


@dataclass
class ProcessOutcome:
    returncode: int | None
    timed_out: bool
    stdout_lines: list[str]
    stderr_tail: str
    wall_seconds: float


class _JobObject:
    """A Windows Job Object that kills every process in it when closed. On
    other platforms (tests on CI) it does nothing and the process is killed
    directly."""

    def __init__(self, memory_limit: int | None):
        self.handle = None
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            return

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kill_on_close, process_memory = 0x2000, 0x0100
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = kill_on_close | (process_memory if memory_limit else 0)
        if memory_limit:
            info.ProcessMemoryLimit = memory_limit
        extended_limit_information = 9
        k32.SetInformationJobObject(handle, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info))
        self._k32 = k32
        self.handle = handle

    def assign(self, proc: subprocess.Popen) -> None:
        if self.handle:
            self._k32.AssignProcessToJobObject(self.handle, int(proc._handle))  # Popen's own process handle

    def kill(self) -> None:
        if self.handle:
            self._k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


def run_process(cmd: Sequence[str], *, cwd: Path, timeout_s: float, env: dict | None = None,
                on_line: Callable[[str], None] | None = None,
                memory_limit: int | None = MEMORY_LIMIT_BYTES) -> ProcessOutcome:
    """Run `cmd`, streaming stdout lines to `on_line`, and kill it (and anything it started) after `timeout_s`."""
    started = time.monotonic()
    job = _JobObject(memory_limit)
    try:
        proc = subprocess.Popen(list(cmd), cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, errors="replace", creationflags=NO_WINDOW)
        job.assign(proc)
        lines: list[str] = []
        err_chunks: list[str] = []

        def pump_out():
            for line in proc.stdout:
                lines.append(line.rstrip("\n"))
                if on_line:
                    on_line(line.rstrip("\n"))

        def pump_err():
            err_chunks.append(proc.stderr.read())

        threads = [threading.Thread(target=pump_out, daemon=True), threading.Thread(target=pump_err, daemon=True)]
        for t in threads:
            t.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            job.kill()
            proc.kill()
            proc.wait()
        for t in threads:
            t.join(timeout=5)
        return ProcessOutcome(proc.returncode, timed_out, lines, "".join(err_chunks)[-3000:],
                              round(time.monotonic() - started, 3))
    finally:
        job.close()


# --- cases ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseSpec:
    """One PSS/E run: the model's records on the rig, and the disturbance to play back.

    `segments` is [[t_start, v_pu, f_hz], ...] starting at t = 0; each holds until the next one starts. A fourth
    field "ramp" makes the playback reach that point in a straight line instead of a step. `repeat` > 0 makes an
    otherwise identical case miss the cache (repeatability checks).
    """

    records: tuple[str, ...]
    segments: tuple[tuple, ...]
    t_end: float
    dlls: tuple[str, ...] = ()
    rig: tuple[tuple[str, object], ...] = ()
    delt: float = DEFAULT_DELT
    freq_filter: float = DEFAULT_FREQ_FILTER
    run_every_step: bool = False
    expect_ncon: int = 0
    repeat: int = 0
    label: str = ""

    def job_fields(self) -> dict:
        return {
            "records": list(self.records),
            "segments": [list(s) for s in self.segments],
            "t_end": self.t_end,
            "dlls": list(self.dlls),
            "rig": dict(self.rig),
            "delt": self.delt,
            "freq_filter": self.freq_filter,
            "run_every_step": self.run_every_step,
            "expect_ncon": self.expect_ncon,
            "repeat": self.repeat,
        }


@dataclass
class CaseResult:
    spec: CaseSpec
    key: str
    status: str  # ok | run_error | init_error | dyre_error | dll_error | exception | timeout | crashed
    meta: dict
    time: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)
    f_hz: list[float] = field(default_factory=list)
    p: list[float] = field(default_factory=list)
    q: list[float] = field(default_factory=list)
    log: str = ""
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def summary(self) -> dict:
        return {"key": self.key, "label": self.spec.label, "status": self.status, "cached": self.cached,
                "error": self.meta.get("error"), "wall_seconds": self.meta.get("wall_seconds")}


def _file_hash(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "missing"


def _read_csv(path: Path) -> dict[str, list[float]]:
    cols: dict[str, list[float]] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for name in reader.fieldnames or []:
            cols[name] = []
        for row in reader:
            for name, val in row.items():
                cols[name].append(float(val) if val not in ("", None) else float("nan"))
    return cols


class Session:
    """Runs cases against one PSS/E selection. Results are cached under
    `root/cache/<key>/`, so a repeated case (or a resumed run) costs nothing."""

    def __init__(self, selection, root: Path, *, workers: int = 4, env: dict | None = None,
                 on_event: Callable[[dict], None] | None = None):
        self.selection = selection
        # Absolute: workers run with the case folder as their working directory, so a relative root would
        # be resolved a second time from there ("can't open file ...\out\work\cache\<key>.partial\out\...").
        self.root = Path(root).resolve()
        self.workers = max(1, workers)
        self.env = env
        self.on_event = on_event
        self._capacity = threading.Semaphore(self.workers)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._worker_script = stage_worker(self.root / "worker")
        self._worker_hash = worker_hash()
        self.cases_run = 0
        self.cases_cached = 0

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def case_key(self, spec: CaseSpec) -> str:
        payload = spec.job_fields()
        payload["dll_hashes"] = [_file_hash(d) for d in spec.dlls]
        payload["psse"] = [self.selection.version, self.selection.install_dir, self.selection.pspy_folder]
        payload["worker"] = self._worker_hash
        blob = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:24]

    def _emit(self, **event):
        if self.on_event:
            self.on_event(event)

    def run_many(self, specs: Sequence[CaseSpec]) -> list[CaseResult]:
        if not specs:
            return []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(self.run_one, specs))

    def run_one(self, spec: CaseSpec) -> CaseResult:
        key = self.case_key(spec)
        case_dir = self.root / "cache" / key
        if (case_dir / "meta.json").exists():
            result = self._load(spec, key, case_dir)
            result.cached = True
            with self._lock:
                self.cases_cached += 1
            self._emit(kind="case", key=key, label=spec.label, status=result.status, cached=True)
            return result
        if self._cancel.is_set():
            return CaseResult(spec, key, "cancelled", {})
        for attempt in range(LICENSE_RETRIES + 1):
            with self._capacity:
                if self._cancel.is_set():
                    return CaseResult(spec, key, "cancelled", {})
                result = self._execute(spec, key, case_dir)
            if not _license_failure(result) or attempt == LICENSE_RETRIES:
                break
            self._shrink_capacity()
            time.sleep(2.0 * (attempt + 1))
        with self._lock:
            self.cases_run += 1
        self._emit(kind="case", key=key, label=spec.label, status=result.status, cached=False)
        return result

    def _shrink_capacity(self):
        """A license refused a seat: hold one slot of the pool for the rest of the session."""
        with self._lock:
            if self.workers > 1:
                self.workers -= 1
                if not self._capacity.acquire(blocking=False):
                    threading.Thread(target=self._capacity.acquire, daemon=True).start()
                self._emit(kind="license_backoff", workers=self.workers)

    def _execute(self, spec: CaseSpec, key: str, case_dir: Path) -> CaseResult:
        tmp = case_dir.with_name(key + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        job = spec.job_fields()
        job.update(schema=1, case_id=key, out_dir=str(tmp), psse_root=self.selection.install_dir,
                   pspy_folder=self.selection.pspy_folder)
        job_path = tmp / "job.json"
        job_path.write_text(json.dumps(job, indent=1))
        timeout = max(MIN_TIMEOUT_S, TIMEOUT_PER_SIM_SECOND * spec.t_end)
        self._emit(kind="case_start", key=key, label=spec.label)
        outcome = run_process([self.selection.python_exe, "-I", str(self._worker_script), "run", str(job_path)],
                              cwd=tmp, timeout_s=timeout, env=self.env)
        meta_path = tmp / "meta.json"
        if outcome.timed_out:
            meta = {"status": "timeout", "error": f"no result within {timeout:.0f} s; the process was stopped"}
        elif not meta_path.exists():
            meta = {"status": "crashed",
                    "error": f"the PSS/E process ended (exit code {outcome.returncode}) without writing a result",
                    "stderr": outcome.stderr_tail}
        else:
            meta = json.loads(meta_path.read_text())
        meta.setdefault("wall_seconds", outcome.wall_seconds)
        meta["process_wall_seconds"] = outcome.wall_seconds
        _reject_ignored_record(tmp, meta)
        meta_path.write_text(json.dumps(meta, indent=1))
        if _license_failure_meta(meta):
            # Not a property of the case: do not cache it.
            result = self._load(spec, key, tmp)
            shutil.rmtree(tmp, ignore_errors=True)
            return result
        shutil.rmtree(case_dir, ignore_errors=True)
        _publish(tmp, case_dir)
        return self._load(spec, key, case_dir)

    @staticmethod
    def _load(spec: CaseSpec, key: str, case_dir: Path) -> CaseResult:
        meta = json.loads((case_dir / "meta.json").read_text())
        result = CaseResult(spec, key, meta.get("status", "exception"), meta)
        csv_path = case_dir / "result.csv"
        if csv_path.exists():
            cols = _read_csv(csv_path)
            result.time, result.v, result.f_hz = cols.get("time", []), cols.get("V", []), cols.get("F_HZ", [])
            result.p, result.q = cols.get("P", []), cols.get("Q", [])
        log_path = case_dir / "psse.log"
        if log_path.exists():
            result.log = log_path.read_text(errors="replace")
        return result


def _publish(tmp: Path, case_dir: Path):
    """Move a finished case folder into the cache.

    On Windows the rename can be refused (PermissionError) for a moment after the worker exits, while
    antivirus or the search indexer still has one of the new files open; a case that ends in milliseconds,
    such as a model PSS/E cannot find, hits this most. Retry briefly instead of losing the case."""
    for attempt in range(PUBLISH_RETRIES):
        try:
            tmp.replace(case_dir)
            return
        except PermissionError:
            if attempt == PUBLISH_RETRIES - 1:
                raise
            time.sleep(PUBLISH_WAIT_S * (attempt + 1))


def _reject_ignored_record(case_dir: Path, meta: dict):
    """PSS/E 35.6 answers an unknown model with `RECORD IGNORED` and a zero return code, then simulates the load
    without it. Every later case would "ride through" a model that is not there, so the case is not ok."""
    if meta.get("status") in ("timeout", "dll_error", "dyre_error", "cancelled"):
        return
    log = case_dir / "psse.log"
    if not log.exists():
        return
    codes = {f.code for f in parse_log(log.read_text(errors="replace"))}
    if "record_ignored" in codes:
        meta["status"] = "dyre_error"
        meta["error"] = "PSS/E ignored the dynamics record (RECORD IGNORED): the model is not known to it"
    elif "model_not_accessible" in codes:
        meta["status"] = "dyre_error"
        meta["error"] = ("PSS/E reports the model as not accessible (NOT ACCESSIBLE): its DLL is missing or does "
                         "not match this PSS/E version")


def _license_failure_meta(meta: dict) -> bool:
    return "psseinit returned" in (meta.get("error") or "")


def _license_failure(result: CaseResult) -> bool:
    return _license_failure_meta(result.meta)


def describe(result: CaseResult) -> dict:
    d = result.summary()
    d["spec"] = asdict(result.spec)
    return d
