"""The PsseRunner interface: run one load-model block's .dyr text against a
fault scenario and get back a dense time-series result.

MockPsseRunner is implemented here - it recognises which registered load
model wrote the record (load_models.find_model_for_dyr), parses it back with
that model's `parse_dyr_record`, and runs the model's own analytic `simulate`
hook, resampled onto a dense fixed-dt series to look like real channel output.
The real PSS/E runner is blackbox.runner.PsseSubprocessRunner (one PSS/E
process per case on the black-box validation rig); get_runner("psse") returns
it once a PSS/E install is selected. dev/validation/sweep.py, dev/validation/checks.py, and every CLI
command depend only on the PsseRunner protocol, never on a concrete class.

MockPsseRunner is NOT a substitute for a real PSS/E validation run - see
src/dev/cli/docs/runners.md (the `PsseRunner` contract) for why (it computes from each model's simplified analytic engine -
for PERC1, the same one ui/main_window.py's live chart uses - not the compiled DLL).
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from load_models import find_model_for_dyr
from load_models.base import FAULT_START

RESAMPLE_DT_S = 0.01
# Long (frequency) runs are resampled more coarsely so a result stays ~5000 points.
RESAMPLE_MAX_POINTS = 5000


@dataclass(frozen=True)
class FaultScenario:
    """One constant disturbance. A voltage event sets `fault_voltage_pu`
    (>1.0 = swell, <1.0 = sag); a frequency event sets `fault_frequency_hz`
    instead and leaves voltage at nominal."""

    id: str
    fault_start_s: float
    fault_duration_s: float
    fault_voltage_pu: float = 1.0
    description: str = ""
    fault_frequency_hz: float | None = None

    @property
    def event_kind(self) -> str:
        return "frequency" if self.fault_frequency_hz is not None else "voltage"

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "fault_start_s": self.fault_start_s,
            "fault_duration_s": self.fault_duration_s,
            "fault_voltage_pu": self.fault_voltage_pu,
            "description": self.description,
        }
        if self.fault_frequency_hz is not None:
            d["fault_frequency_hz"] = self.fault_frequency_hz
        return d

    @classmethod
    def from_dict(cls, d: dict) -> FaultScenario:
        frequency = d.get("fault_frequency_hz")
        return cls(
            id=d["id"],
            fault_start_s=float(d["fault_start_s"]),
            fault_duration_s=float(d["fault_duration_s"]),
            fault_voltage_pu=float(d.get("fault_voltage_pu", 1.0)),
            description=d.get("description", ""),
            fault_frequency_hz=float(frequency) if frequency is not None else None,
        )


@dataclass(frozen=True)
class SimulationResult:
    case_id: str
    block_name: str
    scenario_id: str
    time_s: list
    voltage_pu: list
    active_power_pu: list
    reactive_power_pu: list | None
    tripped: bool
    trip_time_s: float | None
    trip_type: str | None  # "undervoltage" | "overvoltage" | "underfrequency" | "overfrequency" | None
    reconnect_time_s: float | None
    final_power_pu: float | None
    runner_id: str
    raw_case_path: str | None
    dyr_text_sha256: str | None
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    frequency_hz: list | None = None  # populated for frequency events

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "block_name": self.block_name,
            "scenario_id": self.scenario_id,
            "time_s": list(self.time_s),
            "voltage_pu": list(self.voltage_pu),
            "active_power_pu": list(self.active_power_pu),
            "reactive_power_pu": list(self.reactive_power_pu) if self.reactive_power_pu is not None else None,
            "tripped": self.tripped,
            "trip_time_s": self.trip_time_s,
            "trip_type": self.trip_type,
            "reconnect_time_s": self.reconnect_time_s,
            "final_power_pu": self.final_power_pu,
            "runner_id": self.runner_id,
            "raw_case_path": self.raw_case_path,
            "dyr_text_sha256": self.dyr_text_sha256,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "frequency_hz": list(self.frequency_hz) if self.frequency_hz is not None else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SimulationResult:
        return cls(
            case_id=d["case_id"],
            block_name=d["block_name"],
            scenario_id=d["scenario_id"],
            time_s=list(d["time_s"]),
            voltage_pu=list(d["voltage_pu"]),
            active_power_pu=list(d["active_power_pu"]),
            reactive_power_pu=list(d["reactive_power_pu"]) if d.get("reactive_power_pu") is not None else None,
            tripped=bool(d["tripped"]),
            trip_time_s=d.get("trip_time_s"),
            trip_type=d.get("trip_type"),
            reconnect_time_s=d.get("reconnect_time_s"),
            final_power_pu=d.get("final_power_pu"),
            runner_id=d["runner_id"],
            raw_case_path=d.get("raw_case_path"),
            dyr_text_sha256=d.get("dyr_text_sha256"),
            warnings=list(d.get("warnings", [])),
            metadata=dict(d.get("metadata", {})),
            frequency_hz=list(d["frequency_hz"]) if d.get("frequency_hz") is not None else None,
        )


@runtime_checkable
class PsseRunner(Protocol):
    def run(
        self,
        raw_case_path: str | None,
        dyr_text: str,
        scenario: FaultScenario,
        *,
        block_name: str,
        case_id: str,
    ) -> SimulationResult: ...


def _interp(points, t):
    if t <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in itertools.pairwise(points):
        if t0 <= t <= t1:
            if t1 == t0:
                return v1
            frac = (t - t0) / (t1 - t0)
            return v0 + frac * (v1 - v0)
    return points[-1][1]


def _resample(points, sim_end: float, dt: float = RESAMPLE_DT_S):
    n_steps = max(round(sim_end / dt), 1)
    times = [round(i * dt, 6) for i in range(n_steps + 1)]
    # Rounding to 6 places can leave the last sample a hair short of sim_end;
    # that is the end, not a reason for an extra sample.
    if times[-1] < round(sim_end, 6) - 1e-6:
        times.append(round(sim_end, 6))
    else:
        times[-1] = round(sim_end, 6)
    values = [_interp(points, t) for t in times]
    return times, values


class MockPsseRunner:
    """Runs the record's own load model's analytic `simulate` hook as a
    stand-in for a real PSS/E dynamic solve.

    Ignores `scenario.fault_start_s`: analytic simulators always start the
    event at load_models.base.FAULT_START (0.5 s), so only
    fault_duration_s/fault_voltage_pu are honored. This is documented, not a
    silent gap - see `runner_id="mock"` and the warnings this run adds when
    fault_start_s differs from FAULT_START.

    Parses `dyr_text` back into a CON dict with the model's own
    `parse_dyr_record`, so it is exercised against the exact artifact a real
    run would consume, never a shortcut that could silently diverge from what
    gets exported. Raises ValueError if the record's model has no parser or
    simulator."""

    runner_id = "mock"

    def run(
        self,
        raw_case_path: str | None,
        dyr_text: str,
        scenario: FaultScenario,
        *,
        block_name: str,
        case_id: str,
    ) -> SimulationResult:
        model = find_model_for_dyr(dyr_text)
        if not model.can_run_mock:
            raise ValueError(
                f"load model {model.id!r} cannot be mock-run: it needs both parse_dyr_record and simulate hooks"
            )
        cons = model.parse_dyr_record(dyr_text)
        if scenario.event_kind == "frequency":
            if model.simulate_frequency is None:
                raise ValueError(f"load model {model.id!r} has no simulate_frequency hook for frequency scenarios")
            sim = model.simulate_frequency(cons, scenario.fault_duration_s, scenario.fault_frequency_hz)
        else:
            sim = model.simulate(cons, scenario.fault_duration_s, scenario.fault_voltage_pu)

        dt = max(RESAMPLE_DT_S, sim["sim_end"] / RESAMPLE_MAX_POINTS)
        time_s, voltage_pu = _resample(sim["v_points"], sim["sim_end"], dt)
        _, active_power_pu = _resample(sim["p_points"], sim["sim_end"], dt)
        frequency_hz = _resample(sim["f_points"], sim["sim_end"], dt)[1] if "f_points" in sim else None

        markers = sim.get("markers", {})
        warnings = []
        if abs(scenario.fault_start_s - FAULT_START) > 1e-9:
            warnings.append(
                f"MockPsseRunner ignores fault_start_s={scenario.fault_start_s} "
                f"(analytic simulators always start the fault at {FAULT_START}s)"
            )

        return SimulationResult(
            case_id=case_id,
            block_name=block_name,
            scenario_id=scenario.id,
            time_s=time_s,
            voltage_pu=voltage_pu,
            active_power_pu=active_power_pu,
            reactive_power_pu=None,
            tripped=bool(sim["trips"]),
            trip_time_s=markers.get("trip_time"),
            trip_type=sim["trip_type"],
            reconnect_time_s=markers.get("reconnect_end"),
            final_power_pu=active_power_pu[-1] if active_power_pu else None,
            runner_id=self.runner_id,
            raw_case_path=raw_case_path,
            dyr_text_sha256=hashlib.sha256(dyr_text.encode("utf-8")).hexdigest(),
            warnings=warnings,
            metadata={"engine": f"{model.id}.simulate", "model_id": model.id},
            frequency_hz=frequency_hz,
        )


def get_runner(name: str) -> PsseRunner:
    """name in {"mock", "psse"}. "psse" raises NotImplementedError (the
    blackbox.runner.PsseNotConfigured subclass) until a PSS/E install is
    selected - see blackbox/runner.py for where the selection comes from."""
    if name == "mock":
        return MockPsseRunner()
    if name == "psse":
        from blackbox.runner import PsseSubprocessRunner

        return PsseSubprocessRunner.from_environment()
    raise ValueError(f"unknown runner {name!r}; expected 'mock' or 'psse'")
