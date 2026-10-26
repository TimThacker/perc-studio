"""Turning a case's PSS/E log and status into findings the report and the
diagnosis playbook can act on. Patterns are data: add a row to PATTERNS when a
new PSS/E message turns up."""

from __future__ import annotations

import re
from dataclasses import dataclass

# (code, regex, what it means)
PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("model_not_found", r"(?i)not found in (the )?(model )?librar|model .* not found|no such model",
     "PSS/E could not find the model: a DLL is missing, built for another PSS/E version, or the name is wrong."),
    ("record_ignored", r"RECORD IGNORED",
     ("PSS/E skipped a dynamics record and went on without it, so the model was never attached. Real PSS/E does "
      "this for a model it does not know (DLL missing or built for another version, or a wrong name) and returns "
      "no error.")),
    ("model_not_accessible", r'(?i)USER DEFINED LOAD RELATED MODEL ".*" NOT ACCESSIBLE',
     ("PSS/E could not find the user model named in the record: its DLL was not added, was built for another "
      "PSS/E version, or the model name is wrong. PSS/E carries on without the model and returns no error.")),
    ("dll_not_loaded", r"(?i)Library not found",
     ("It is usually built for another PSS/E version (35 and 36 DLLs are not "
      "interchangeable), or the path is wrong.")),
    ("invalid_file_type", r"(?i)invalid file type",
     "PSS/E could not read a file it was given (often PSSBIN missing from PATH)."),
    ("init_suspect", r"(?i)initial conditions suspect",
     "PSS/E found states that are not at rest at t = 0: the model does not initialize to the power flow."),
    ("network_not_converged", r"(?i)network not converged",
     "The network solution failed during the simulation."),
    ("fortran_error", r"(?i)forrtl|severe \(\d+\)",
     "The model's Fortran runtime reported an error."),
    ("dyre_error", r"(?i)error.*(dyre|dynamics data)|(dyre|dynamics data).*error",
     "PSS/E reported an error while reading the dynamics data."),
    ("con_out_of_range", r"(?i)con\(.*\).*(out of range|invalid)|invalid.*con",
     "PSS/E rejected a CON value."),
)

STATUS_TEXT = {
    "ok": "ran",
    "run_error": "PSS/E stopped during the simulation",
    "init_error": "PSS/E could not initialize the dynamics",
    "dyre_error": "PSS/E could not read the dynamics data",
    "dll_error": "PSS/E could not load a DLL",
    "exception": "the worker failed",
    "timeout": "no answer in time; stopped",
    "crashed": "the PSS/E process ended without a result",
    "cancelled": "cancelled",
}


@dataclass(frozen=True)
class Finding:
    code: str
    meaning: str
    line: str


def parse_log(text: str) -> list[Finding]:
    found, seen = [], set()
    lines = text.splitlines()
    for code, pattern, meaning in PATTERNS:
        rx = re.compile(pattern)
        for i, line in enumerate(lines):
            if rx.search(line):
                if code not in seen:
                    context = " ".join(ln.strip() for ln in lines[i:i + 3] if ln.strip())
                    found.append(Finding(code, meaning, context[:300]))
                    seen.add(code)
                break
    return found


def suspect_states(text: str) -> list[str]:
    """The state lines PSS/E lists after INITIAL CONDITIONS SUSPECT."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"(?i)initial conditions suspect", line):
            out = []
            for ln in lines[i + 1:i + 30]:
                if not ln.strip():
                    if out:
                        break
                    continue
                out.append(ln.strip())
            return out[:20]
    return []
