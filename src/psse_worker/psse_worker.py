# ruff: noqa: S110, UP031, FURB122 - Python 3.7-compatible, stdlib-only; cleanup steps must never stop a run
"""PSS/E side of black-box validation: runs ONE case and exits.

This file runs under the Python that the user's PSS/E install supports, not
under the app's own Python. It must therefore use the standard library only
and Python 3.7 syntax (no walrus, no `match`, no `X | Y` annotations). The app
copies it into a fresh work folder and starts it as

    <pssepython> -I psse_worker.py probe <out.json> <psse_root> <PSSPYxx>
    <pssepython> -I psse_worker.py run <job.json>

`probe` proves an install works: import psspy, psseinit, psseversion, and a
power flow on the rig with no dynamics. `run` builds the rig, reads the job's
.dyr records (and DLLs), plays back the job's voltage/frequency profile and
writes `result.csv`, `meta.json` and `psse.log` to the job's `out_dir`.

The rig is the one proven in the PSS/E validation library: bus 100001 (138 kV swing
bus) with one load, and one machine driven by PSS/E's playback model PLBVF1
(MBASE 10,000 MVA, ZSORCE 0.01 pu), so bus voltage and frequency follow the
profile exactly. Loads are converted to constant power before the model under
test takes over, and network frequency dependence is on.

Quirks this file handles (each measured in PSS/E):
* `dyre_new` fails with "Invalid file type" unless PSSBIN is on PATH;
* PLBVF1 multiplies the played-back voltage by f/60 (pre-divided here), reads
  its file from the working folder, and takes names of at most 12 characters;
* model memory survives psseinit (36.7), so the app runs one case per process;
* calling psspy.run more often changes some DLL models' ramps, so by default
  run() is called only at the profile's breakpoints and the trace is read
  from the channel output file, written every time step.
"""

import json
import math
import os
import sys
import time
import traceback

SCHEMA = 1
SOURCE_BUS = 100001
SBASE = 100.0
DELT = 1.0 / 240.0
FREQ_FILTER = 0.033333
PLB_NAME = "pbvalid"  # PLBVF1 file names must be <= 12 characters
EDGE = 1e-4  # width of a step edge in the playback file
CHANGE_TOL = 1e-6


def _emit(event, **fields):
    """One JSON line on stdout: the app streams these as progress."""
    fields["event"] = event
    sys.stdout.write(json.dumps(fields) + "\n")
    sys.stdout.flush()


def _suppress_crash_dialogs():
    """Stop Windows from opening a crash or 'insert disk' dialog when a user
    DLL fails, so the app's timeout and exit code see the failure instead."""
    if os.name != "nt":
        return
    try:
        import ctypes

        sem_failcriticalerrors, sem_nogpfaulterrorbox = 0x0001, 0x0002
        ctypes.windll.kernel32.SetErrorMode(sem_failcriticalerrors | sem_nogpfaulterrorbox)
    except Exception:  # noqa: BLE001 - best effort; never block a run on this
        pass


def _bootstrap(psse_root, pspy_folder):
    dirs = [os.path.join(psse_root, d) for d in ("PSSBIN", "PSSLIB", pspy_folder)]
    for d in dirs:
        if os.path.isdir(d):
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)
            if d not in sys.path:
                sys.path.append(d)
    os.environ["PATH"] = ";".join(dirs) + ";" + os.environ.get("PATH", "")
    import psspy

    try:
        import redirect

        redirect.psse2py()
    except Exception:  # noqa: BLE001 - output redirection is optional
        pass
    return psspy


def _version(psspy):
    raw = psspy.psseversion()
    fields = [str(v).strip() for v in raw]
    try:
        major, minor = int(raw[1]), int(raw[2])
    except (TypeError, ValueError, IndexError):
        major = minor = None
    patch = None
    if len(raw) > 3:
        try:
            patch = int(raw[3])
        except (TypeError, ValueError):
            patch = None
    return {"raw": fields, "major": major, "minor": minor, "patch": patch}


def _check(ierr, what):
    if ierr != 0:
        raise RuntimeError("%s failed: ierr=%s" % (what, ierr))


def _build_rig(psspy, rig):
    bus = int(rig.get("bus", SOURCE_BUS))
    v0 = float(rig.get("v0", 1.0))
    p_mw, q_mvar = float(rig.get("p_mw", 100.0)), float(rig.get("q_mvar", 20.0))
    lid = str(rig.get("load_id", "1"))
    owner, zone, area = int(rig.get("owner", 1)), int(rig.get("zone", 1)), int(rig.get("area", 1))
    _check(psspy.newcase_2([0, 0], SBASE, 60.0, "Black-box validation", "PLBVF1 single bus"), "newcase_2")
    _check(psspy.bus_data_4(bus, 0, [3, area, zone, owner], [float(rig.get("base_kv", 138.0)), v0, 0.0, 1.1, 0.9, 1.1, 0.9],
                            "SRC"), "bus_data_4")
    _check(psspy.load_data_6(bus, lid, [1, area, zone, owner, 1, 0, 0], [p_mw, q_mvar, 0, 0, 0, 0, 0, 0], "UNDERTEST"),
           "load_data_6")
    _check(psspy.plant_data_4(bus, 0, [0, 0], [v0, 100.0]), "plant_data_4")
    _check(psspy.machine_data_2(bus, "1", [1, 1, 0, 0, 0, 0],
                                [p_mw, q_mvar, 9999, -9999, 9999, -9999, 10000.0, 0, 0.01, 0, 0, 1, 1, 0, 0, 0, 1]),
           "machine_data_2")
    _check(psspy.fnsl([0, 0, 0, 1, 1, 0, 99, 0]), "fnsl")
    return bus, lid


def _prepare_dynamics(psspy):
    _check(psspy.cong(0), "cong")
    for step in (1, 2, 3):
        ierr = psspy.conl(0, 1, step, [0, 0], [100.0, 0.0, 0.0, 100.0])
        ierr = ierr[0] if isinstance(ierr, (tuple, list)) else ierr
        _check(ierr, "conl(%d)" % step)
    _check(psspy.ordr(0), "ordr")
    _check(psspy.fact(), "fact")
    _check(psspy.tysl(0), "tysl")


def _profile_points(segments, t_end):
    """[[t_start, v_pu, f_hz], ...] -> playback rows with EDGE-wide steps,
    extended past t_end so PLBVF1 never runs off the end of its file. A
    segment with a fourth field "ramp" is reached by a straight line from the
    previous point instead of a step."""
    rows = []
    prev = None
    for seg in segments:
        t, v, f = float(seg[0]), float(seg[1]), float(seg[2])
        ramp = len(seg) > 3 and seg[3] == "ramp"
        if prev is not None and t > 0 and not ramp:
            rows.append((t, prev[0], prev[1]))
            rows.append((t + EDGE, v, f))
        else:
            rows.append((t, v, f))
        prev = (v, f)
    rows.append((max(float(t_end), rows[-1][0]) + 10.0, prev[0], prev[1]))
    return rows


def _write_plb(path, rows):
    with open(path, "w") as fh:
        for t, v, f_hz in rows:
            f_pu = f_hz / 60.0
            fh.write("%.6f, %.8f, %.8f\n" % (t, v / f_pu, f_pu))


def _run_times(segments, t_end, every_step, delt):
    if every_step:
        n = round(float(t_end) / delt)
        return [round((i + 1) * delt, 9) for i in range(n)]
    times = set()
    for seg in segments:
        t = float(seg[0])
        if 0 < t < t_end:
            times.add(round(t, 9))
            times.add(round(t + EDGE, 9))
    times.add(float(t_end))
    return sorted(times)


def _read_outfile(path):
    """({name: [values]}, reader) from a PSS/E channel output file.

    The app's own reader (outx.py, staged next to this file and needing nothing but the standard
    library) is tried first. dyntools is only the fallback for a file layout the reader does not
    recognize (it raises OutxFormatError), for example from a PSS/E version it has not been checked
    against; it needs PSS/E's DLLs and fails confusingly without them (validation finding F2).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.append(here)  # python -I does not put the script's folder on the path
    try:
        from outx import OutxFormatError, read_outx

        try:
            data = read_outx(path)
            return dict(data.channels, time=data.time), "internal"
        except OutxFormatError:
            pass
    except ImportError:
        pass
    import dyntools

    chnf = dyntools.CHNF(path)
    _title, ch_id, ch_data = chnf.get_data()
    out = {"time": list(ch_data["time"])}
    for key, name in ch_id.items():
        if key == "time":
            continue
        out[str(name).strip()] = list(ch_data[key])
    return out, "dyntools"


def _compress(columns, rows):
    if len(rows) <= 2:
        return rows
    kept, prev = [rows[0]], rows[0]
    for r in rows[1:]:
        moved = False
        for a, b in zip(r[1:], kept[-1][1:]):
            if (a is None) != (b is None) or (a is not None and not (math.isnan(a) and math.isnan(b))
                                              and (math.isnan(a) or math.isnan(b) or abs(a - b) > CHANGE_TOL)):
                moved = True
                break
        if moved:
            if prev is not kept[-1]:
                kept.append(prev)
            kept.append(r)
        prev = r
    if kept[-1] is not rows[-1]:
        kept.append(rows[-1])
    return kept


def _fmt(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    return "%.7g" % x


def _route_output(psspy, log_path):
    for fn in (psspy.report_output, psspy.progress_output, psspy.alert_output, psspy.prompt_output):
        fn(2, log_path, [0, 0])


def _flush_output(psspy):
    psspy.progress_output(6, "", [0, 0])
    psspy.report_output(6, "", [0, 0])


def _read_text(path):
    try:
        with open(path, errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def cmd_probe(out_path, psse_root, pspy_folder):
    result = {"schema": SCHEMA, "ok": False, "python": sys.version.split()[0],
              "bits": 64 if sys.maxsize > 2 ** 32 else 32, "psse_root": psse_root, "pspy_folder": pspy_folder}
    try:
        _suppress_crash_dialogs()
        psspy = _bootstrap(psse_root, pspy_folder)
        result["stage"] = "psseinit"
        ierr = psspy.psseinit(1000)
        if ierr not in (0, None):
            raise RuntimeError("psseinit returned ierr=%s (often a license problem)" % ierr)
        result["version"] = _version(psspy)
        result["stage"] = "power flow"
        log_path = os.path.abspath("probe.log")
        _route_output(psspy, log_path)
        _build_rig(psspy, {})
        _flush_output(psspy)
        result["ok"] = True
        result["stage"] = "done"
        try:
            psspy.pssehalt_2()
        except Exception:  # noqa: BLE001
            pass
    except BaseException as exc:  # noqa: BLE001 - report every failure, including SystemExit from psspy
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["traceback"] = traceback.format_exc()[-3000:]
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=1)
    return 0 if result["ok"] else 1


def cmd_run(job_path):
    with open(job_path) as fh:
        job = json.load(fh)
    out_dir = os.path.abspath(job["out_dir"])
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    meta = {"schema": SCHEMA, "case_id": job.get("case_id"), "status": "exception", "python": sys.version.split()[0]}
    log_path = os.path.join(out_dir, "psse.log")
    started = time.time()
    psspy = None
    try:
        _suppress_crash_dialogs()
        os.chdir(out_dir)  # PLBVF1 reads its file from the working folder
        psspy = _bootstrap(job["psse_root"], job["pspy_folder"])
        ierr = psspy.psseinit(1000)
        if ierr not in (0, None):
            raise RuntimeError("psseinit returned ierr=%s (often a license problem)" % ierr)
        meta["version"] = _version(psspy)
        _route_output(psspy, log_path)
        _emit("stage", stage="rig")
        rig = job.get("rig", {})
        bus, lid = _build_rig(psspy, rig)
        _prepare_dynamics(psspy)

        segments = job["segments"]
        t_end = float(job["t_end"])
        delt = float(job.get("delt", DELT))
        _write_plb(os.path.join(out_dir, PLB_NAME + ".plb"), _profile_points(segments, t_end))
        dyr_path = os.path.join(out_dir, "case.dyr")
        with open(dyr_path, "w") as fh:
            fh.write("%d 'PLBVF1' '1' 1 1 '%s' 1.0 1.0 0.0 0.0 /\n" % (bus, PLB_NAME))
            for rec in job["records"]:
                fh.write(rec.replace("{BUS}", str(bus)).rstrip() + "\n")

        meta["dll_ierr"] = []
        for dll in job.get("dlls", []):
            meta["dll_ierr"].append(psspy.addmodellibrary(dll))
        if any(e != 0 for e in meta["dll_ierr"]):
            meta["status"] = "dll_error"
            raise _Stop()

        _emit("stage", stage="dyre")
        meta["dyre_ierr"] = psspy.dyre_new([1, 1, 1, 1], dyr_path, "", "", "")
        if meta["dyre_ierr"] != 0:
            meta["status"] = "dyre_error"
            raise _Stop()

        meta["model_name"] = _model_name(psspy, bus, lid)
        meta["con_readback"] = _con_readback(psspy, bus, lid, int(job.get("expect_ncon", 0)))

        _check(psspy.voltage_channel([-1, -1, -1, bus], "V"), "voltage_channel")
        _check(psspy.bus_frequency_channel([-1, bus], "F"), "bus_frequency_channel")
        _check(psspy.load_array_channel([-1, 1, bus], lid, "P"), "load_array_channel(P)")
        _check(psspy.load_array_channel([-1, 2, bus], lid, "Q"), "load_array_channel(Q)")
        _check(psspy.set_netfrq(1), "set_netfrq")
        # INTGAR(2) is the number of channels being recorded: 0 would leave the channel file empty, so every
        # item but the iteration limit and the first four reals stays unchanged (psspy._i / psspy._f).
        _check(psspy.dynamics_solution_param_2([99] + [psspy._i] * 7,
                                               [1.0, 0.0001, delt, float(job.get("freq_filter", FREQ_FILTER))]
                                               + [psspy._f] * 4),
               "dynamics_solution_param_2")

        _emit("stage", stage="initialize")
        out_file = os.path.join(out_dir, "case.outx")
        meta["strt_ierr"] = psspy.strt_2([0, 0], out_file)
        if meta["strt_ierr"] != 0:
            meta["status"] = "init_error"
            raise _Stop()

        _emit("stage", stage="simulate")
        meta["run_error"] = None
        every_step = bool(job.get("run_every_step", False))
        times = _run_times(segments, t_end, every_step, delt)
        meta["run_calls"] = len(times)
        sampled = [_sample(psspy, 0.0)]
        for t in times:
            ierr = psspy.run(0, t, 100000, 1, 0)
            if ierr != 0:
                meta["run_error"] = "psspy.run to t=%g returned ierr=%s" % (t, ierr)
                break
            sampled.append(_sample(psspy, t))

        columns = ["time", "V", "F_HZ", "P", "Q"]
        rows = None
        try:
            data, meta["sampling_reader"] = _read_outfile(out_file)
            rows = [[t, data["V"][i], 60.0 * (1.0 + data["F"][i]), data["P"][i], data["Q"][i]]
                    for i, t in enumerate(data["time"])]
            meta["sampling"] = "outfile"
        except Exception as exc:  # noqa: BLE001 - fall back to the values read at each run() call
            meta["sampling"] = "run_calls"
            meta["sampling_note"] = "channel file unreadable (%s); trace has one row per run() call" % exc
            rows = sampled
        rows = _compress(columns, rows)
        with open(os.path.join(out_dir, "result.csv"), "w") as fh:
            fh.write(",".join(columns) + "\n")
            for r in rows:
                fh.write(",".join(_fmt(x) for x in r) + "\n")
        meta["samples_kept"] = len(rows)
        meta["status"] = "run_error" if meta["run_error"] else "ok"
    except _Stop:
        pass
    except BaseException as exc:  # noqa: BLE001 - record every failure for the app's diagnosis
        meta["error"] = "%s: %s" % (type(exc).__name__, exc)
        meta["traceback"] = traceback.format_exc()[-3000:]
    meta["wall_seconds"] = round(time.time() - started, 3)
    if psspy is not None:
        try:
            _flush_output(psspy)
        except Exception:  # noqa: BLE001
            pass
    with open(os.path.join(out_dir, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    _emit("done", status=meta["status"])
    if psspy is not None:
        try:
            psspy.pssehalt_2()
        except BaseException:  # noqa: BLE001
            pass
    return 0


class _Stop(Exception):
    """A PSS/E step failed in a way meta.json already describes."""


def _sample(psspy, t):
    row = [t]
    for ch in (1, 2, 3, 4):
        ierr, val = psspy.chnval(ch)
        row.append(val if ierr == 0 and val is not None else float("nan"))
    row[2] = 60.0 * (1.0 + row[2]) if not math.isnan(row[2]) else row[2]
    return row


def _model_name(psspy, bus, lid):
    try:
        ierr, name = psspy.lmodnam(bus, lid, "CHARAC")
        return name.strip() if ierr == 0 and name else None
    except Exception:  # noqa: BLE001
        return None


def _con_readback(psspy, bus, lid, ncon):
    """The CONs PSS/E holds for the load's model, when it reports their index."""
    if ncon <= 0:
        return None
    try:
        ierr, con0 = psspy.lmodind(bus, lid, "CHARAC", "CON")
        if ierr != 0 or con0 is None:
            return None
        return [psspy.dsrval("CON", con0 + i)[1] for i in range(ncon)]
    except Exception:  # noqa: BLE001
        return None


def main(argv):
    if len(argv) >= 2 and argv[1] == "probe" and len(argv) == 5:
        return cmd_probe(argv[2], argv[3], argv[4])
    if len(argv) == 3 and argv[1] == "run":
        return cmd_run(argv[2])
    sys.stderr.write("usage: psse_worker.py probe <out.json> <psse_root> <PSSPYxx> | run <job.json>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
