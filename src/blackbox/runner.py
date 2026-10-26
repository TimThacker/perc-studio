"""`PsseSubprocessRunner`: the real `psse.runner.PsseRunner`, built on the
black-box supervisor, so `perc-studio run`, `sweep` and envelope validation can
use PSS/E instead of the mock.

The PSS/E selection comes from the environment (`PERC_STUDIO_PSSE_VERSION`,
`PERC_STUDIO_PSSE_DIR`, optional `PERC_STUDIO_PSSE_PYTHON`, `PERC_STUDIO_PSSE_PSPY`) or, failing
that, from the selection saved by the Black-Box Validation tab. DLLs a model
needs (the PERC1 DLL) come from `PERC_STUDIO_PSSE_DLLS` (separated by `;`).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from psse.runner import FaultScenario, SimulationResult

from . import classify as cl
from .intake import load_targets, place_on_rig, scan_dyr
from .psse_install import PsseSelection, default_install_dir, load_saved_selection
from .supervisor import CaseSpec, Session

OBSERVE_AFTER_S = 10.0


class PsseNotConfigured(NotImplementedError):
    """No PSS/E install has been chosen."""


def configured_selection() -> PsseSelection:
    version = os.environ.get("PERC_STUDIO_PSSE_VERSION")
    if version:
        return PsseSelection(version, os.environ.get("PERC_STUDIO_PSSE_DIR") or default_install_dir(version),
                             os.environ.get("PERC_STUDIO_PSSE_PYTHON", ""), os.environ.get("PERC_STUDIO_PSSE_PSPY", ""))
    saved = load_saved_selection()
    if saved and saved.version and saved.install_dir:
        return saved
    raise PsseNotConfigured(
        "no PSS/E install is selected: choose one in the Black-Box Validation tab, or set PERC_STUDIO_PSSE_VERSION "
        "(and PERC_STUDIO_PSSE_DIR if it is not in the default folder). `perc-studio psse check` tests a selection.")


class PsseSubprocessRunner:
    runner_id = "psse"

    def __init__(self, selection: PsseSelection, *, work_root: Path | None = None, dlls: tuple[str, ...] = (),
                 workers: int = 1):
        self.selection = selection.resolved()
        self.dlls = dlls
        self.session = Session(self.selection, Path(work_root or tempfile.mkdtemp(prefix="perc1_psse_")),
                               workers=workers)

    @classmethod
    def from_environment(cls) -> PsseSubprocessRunner:
        dlls = tuple(d for d in os.environ.get("PERC_STUDIO_PSSE_DLLS", "").split(";") if d)
        return cls(configured_selection(), dlls=dlls)

    def run(self, raw_case_path: str | None, dyr_text: str, scenario: FaultScenario, *, block_name: str,
            case_id: str) -> SimulationResult:
        records = scan_dyr(dyr_text)
        targets = load_targets(records)
        if not targets:
            raise ValueError("the .dyr text has no load-model record")
        placement = place_on_rig(records, targets[0])
        start, end = scenario.fault_start_s, scenario.fault_start_s + scenario.fault_duration_s
        if scenario.event_kind == "frequency":
            level = (1.0, scenario.fault_frequency_hz)
        else:
            level = (scenario.fault_voltage_pu, 60.0)
        segments = ((0.0, 1.0, 60.0), (start, *level), (end, 1.0, 60.0))
        spec = CaseSpec(records=placement.records, segments=segments, t_end=end + OBSERVE_AFTER_S, dlls=self.dlls,
                        rig=tuple(sorted(placement.rig.items())), expect_ncon=placement.expect_ncon,
                        label=f"{case_id}/{block_name}/{scenario.id}")
        res = self.session.run_one(spec)
        if not res.ok:
            raise RuntimeError(f"PSS/E run failed ({res.status}): {res.meta.get('error') or ''}".strip())
        outcome = cl.classify(res, start, end)
        if scenario.event_kind == "frequency":
            trip_type = "underfrequency" if scenario.fault_frequency_hz < 60.0 else "overfrequency"
        else:
            trip_type = "undervoltage" if scenario.fault_voltage_pu < 1.0 else "overvoltage"
        p0 = res.p[0] or 1.0
        return SimulationResult(
            case_id=case_id, block_name=block_name, scenario_id=scenario.id, time_s=res.time, voltage_pu=res.v,
            active_power_pu=[p / p0 for p in res.p], reactive_power_pu=[q / p0 for q in res.q],
            tripped=outcome.tripped, trip_time_s=outcome.trip_time_s,
            trip_type=trip_type if outcome.tripped else None,
            reconnect_time_s=None if outcome.reconnect_s is None else end + outcome.reconnect_s,
            final_power_pu=outcome.final_ratio, runner_id=self.runner_id, raw_case_path=raw_case_path,
            dyr_text_sha256=hashlib.sha256(dyr_text.encode("utf-8")).hexdigest(),
            warnings=list(outcome.notes) + list(placement.flags),
            metadata={"engine": "psse", "psse": res.meta.get("version"), "outcome": outcome.to_dict(),
                      "case_key": res.key},
            frequency_hz=res.f_hz if scenario.event_kind == "frequency" else None,
        )
