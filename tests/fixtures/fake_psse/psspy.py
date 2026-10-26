"""A stand-in for PSS/E's psspy, for testing black-box validation without PSS/E.

It implements only the calls `src/psse_worker/psse_worker.py` makes, and it
"simulates" a single load model read from the case's .dyr file. The fixture
`fake_psse_install` (tests/test_blackbox_*.py) lays this file out as
<root>/PSSPYxx/psspy.py next to `dyntools.py` and `redirect.py`, with a
`version.txt` holding the PSS/E version to report.

Models (record form: `{BUS} 'USRLOD' 'id' '<NAME>' 12 1 0 <NC> 0 0 <CONs> /`):

FAKETRIP   CONs: VUV TUV VOV TOV FLO FHI TF VREC TREC TRAMP NP DELTMAX CADENCE
           Trips when V < VUV for TUV s, V > VOV for TOV s, or f outside
           [FLO, FHI] for TF s. Then reconnects once VREC < V < VOV and
           FLO < f < FHI has held for TREC s, ramping back over TRAMP s.
           P = frac * P0 * V**NP. DELTMAX > 0: the response oscillates when
           the time step is larger than DELTMAX. CADENCE = 1: each run() call
           advances the ramp one extra step (like the PERC1 DLL).
FAKECYCLE  FAKETRIP whose undervoltage trip happens when a sag ends, and only
           if it lasted between TUV and CON 13 s: it rides through shorter and
           longer sags (a deliberately non-monotonic boundary).
FAKEHANG   hangs in strt_2.
FAKECRASH  kills the process in run().
FAKENAN    P becomes NaN once the event starts.
anything else: dyre_new reports the model as missing.

`FAKE_PSSE_LICENSE=fail` in the environment makes psseinit fail.
"""

import itertools
import math
import os
import re
import time as _time

_HERE = os.path.dirname(os.path.abspath(__file__))
KNOWN = ("FAKETRIP", "FAKECYCLE", "FAKEHANG", "FAKECRASH", "FAKENAN")

_S = {}


def _log(text):
    path = _S.get("log")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")


def psseinit(buses=1000):
    if os.environ.get("FAKE_PSSE_LICENSE") == "fail":
        return 5
    _S.clear()
    return 0


def psseversion():
    with open(os.path.join(_HERE, "version.txt")) as fh:
        parts = [int(x) for x in fh.read().strip().split(".")]
    while len(parts) < 3:
        parts.append(0)
    return ("PSS(R)E", parts[0], parts[1], parts[2], "fake", 0)


def pssehalt_2():
    return 0


def report_output(islct, filarg="", options=None):
    if islct == 2:
        _S["log"] = filarg
    return 0


progress_output = alert_output = prompt_output = report_output


def newcase_2(options, sbase, basefreq, title1, title2):
    _S["sbase"] = sbase
    return 0


def bus_data_4(ibus, inode, intgar, realar, name):
    _S["bus"] = ibus
    _S["v0"] = realar[1]
    return 0


def load_data_6(ibus, loadid, intgar, realar, name):
    _S["p0"] = realar[0] / _S["sbase"]
    _S["q0"] = realar[1] / _S["sbase"]
    _S["load_id"] = loadid
    return 0


def plant_data_4(*args):
    return 0


def machine_data_2(*args):
    return 0


def fnsl(options):
    return 0


def cong(option):
    return 0


def conl(*args):
    return 0, 0


def ordr(option):
    return 0


def fact():
    return 0


def tysl(option):
    return 0


def addmodellibrary(path):
    if os.path.exists(path) and "wrongversion" not in os.path.basename(path).lower():
        return 0
    # a DLL built for another PSS/E version fails the same way as a missing one
    _log(f'Messages for api ADDMODELLIBRARY\nLibrary not found   (000352)\n"{path}"')
    return 1


def _tokens(text):
    return re.findall(r"'[^']*'|[^\s,/]+", text)


def dyre_new(options, path, *args):
    with open(path) as fh:
        text = fh.read()
    model = None
    for chunk in text.split("/"):
        toks = _tokens(chunk)
        if len(toks) < 2:
            continue
        name = toks[1].strip("'")
        if name == "PLBVF1":
            _S["plb"] = toks[5].strip("'") + ".plb"
        elif name == "USRLOD":
            model = (toks[3].strip("'"), [float(x) for x in toks[10:]])
    if model is not None and model[0] == "IGNOREDMD":
        # what real PSS/E 35.6 does with a model it does not know: complain in the log, return 0, attach nothing
        text = chunk.strip()
        _log("Input error detected at !\n" + text + "\n\nRECORD IGNORED:\n" + text + " /")
        return 0
    if model is not None and model[0] == "NOACCESSMD":
        # what real PSS/E 35.6 and 36.7 do with a user model whose DLL was not added: note it in the log, return 0
        _log('BUS 100001 [SRC         138.00] LD 1  USER DEFINED LOAD RELATED MODEL "NOACCESSMD" NOT ACCESSIBLE')
        return 0
    if model is None or model[0] not in KNOWN:
        _log(f" MODEL {model[0] if model else '?'} NOT FOUND IN MODEL LIBRARY")
        return 1
    _S["model"], _S["cons"] = model
    _log(f" SUMMARY OF MODELS READ: {model[0]}")
    return 0


def lmodnam(ibus, loadid, kind):
    return (0, _S["model"]) if "model" in _S else (1, None)


def lmodind(ibus, loadid, kind, what):
    return (0, 1) if "model" in _S else (1, None)


def dsrval(kind, index):
    if kind == "CON" and 1 <= index <= len(_S.get("cons", [])):
        return 0, _S["cons"][index - 1]
    return 1, None


def voltage_channel(*args):
    return 0


bus_frequency_channel = load_array_channel = voltage_channel


def set_netfrq(status):
    return 0


_i = -2147483647
_f = -1.0e30


def dynamics_solution_param_2(intgar, realar):
    _S["delt"] = realar[2]
    if intgar[1] != _i:  # INTGAR(2): channels being monitored. 0 is real PSS/E's "record nothing"
        _S["monitored"] = intgar[1]
    return 0


def _read_plb(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            t, v, f = (float(x) for x in line.split(","))
            rows.append((t, v * f, f * 60.0))
    return rows


def _interp(rows, t):
    if t <= rows[0][0]:
        return rows[0][1], rows[0][2]
    for (t0, v0, f0), (t1, v1, f1) in itertools.pairwise(rows):
        if t0 <= t <= t1:
            a = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return v0 + a * (v1 - v0), f0 + a * (f1 - f0)
    return rows[-1][1], rows[-1][2]


def strt_2(options, outfile):
    if _S.get("model") == "FAKEHANG":
        while True:
            _time.sleep(1)
    _S["out"] = outfile
    with open(outfile, "w") as fh:
        fh.write("fake channel file; dyntools.CHNF reads the trace from psspy's memory")
    _S["rows"] = _read_plb(os.path.join(os.getcwd(), _S["plb"]))
    c = list(_S["cons"]) + [0.0] * 16
    _S["c"] = c
    _S.update(t=0.0, frac=1.0, state="on", tuv=0.0, tov=0.0, tf=0.0, trec=0.0, ramp_t=0.0, t_event=None, trace=[])
    _record()
    return 0


def _step(dt, extra_ramp_steps=0):
    c = _S["c"]
    vuv, tuv, vov, tov, flo, fhi, tfd, vrec, trec, tramp, npx, deltmax, _cadence, cycle_max = c[:14]
    t = _S["t"] + dt
    v, f = _interp(_S["rows"], t)
    if _S["t_event"] is None and (abs(v - _S["rows"][0][1]) > 1e-3 or abs(f - _S["rows"][0][2]) > 1e-3):
        _S["t_event"] = t
    state = _S["state"]
    if state in ("on", "ramp"):
        ended_sag = _S["tuv"] if v >= vuv else None
        _S["tuv"] = _S["tuv"] + dt if v < vuv else 0.0
        _S["tov"] = _S["tov"] + dt if v > vov else 0.0
        _S["tf"] = _S["tf"] + dt if (f < flo or f > fhi) else 0.0
        uv_trip = _S["tuv"] >= tuv - 1e-9 and v < vuv
        if _S["model"] == "FAKECYCLE":
            uv_trip = ended_sag is not None and tuv - 1e-9 <= ended_sag <= cycle_max
        if uv_trip or (_S["tov"] >= tov - 1e-9 and v > vov) or (_S["tf"] >= tfd - 1e-9 and (f < flo or f > fhi)):
            _S.update(state="off", frac=0.0, trec=0.0)
    elif state == "off":
        ok = vrec < v < vov and flo < f < fhi
        _S["trec"] = _S["trec"] + dt if ok else 0.0
        if _S["trec"] >= trec - 1e-9:
            _S.update(state="ramp", ramp_t=0.0)
    if _S["state"] == "ramp":
        _S["ramp_t"] += dt * (1 + extra_ramp_steps)
        _S["frac"] = min(1.0, _S["ramp_t"] / tramp) if tramp > 0 else 1.0
        if _S["frac"] >= 1.0:
            _S.update(state="on", tuv=0.0, tov=0.0, tf=0.0)
    p = _S["frac"] * _S["p0"] * (max(v, 0.0) ** npx)
    q = _S["frac"] * _S["q0"] * (max(v, 0.0) ** npx)
    if deltmax > 0 and _S["delt"] > deltmax and _S["t_event"] is not None:
        grow = math.exp(0.8 * (t - _S["t_event"]))
        p += 0.05 * grow * math.sin(2 * math.pi * 3.0 * (t - _S["t_event"]))
    if _S["model"] == "FAKENAN" and _S["t_event"] is not None:
        p = float("nan")
    _S.update(t=t, v=v, f=f, p=p, q=q)


def _record():
    if "v" not in _S:
        v, f = _interp(_S["rows"], 0.0)
        _S.update(v=v, f=f, p=_S["p0"] * (v ** _S["c"][10]), q=_S["q0"] * (v ** _S["c"][10]))
    _S["trace"].append((_S["t"], _S["v"], _S["f"] / 60.0 - 1.0, _S["p"], _S["q"]))


def run(option, tpause, nprt, nplt, crtplt):
    if _S.get("model") == "FAKECRASH":
        os._exit(17)
    delt = _S["delt"]
    first = True
    while _S["t"] < tpause - 1e-9:
        dt = min(delt, tpause - _S["t"])
        extra = 1 if (first and _S["c"][12] == 1 and _S["state"] == "ramp") else 0
        _step(dt, extra)
        first = False
        _record()
    return 0


def chnval(ch):
    vals = {1: _S.get("v"), 2: _S.get("f", 60.0) / 60.0 - 1.0, 3: _S.get("p"), 4: _S.get("q")}
    return 0, vals[ch]
