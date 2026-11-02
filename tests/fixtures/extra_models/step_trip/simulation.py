"""Step-trip response: the block trips if the event crosses a threshold for at least that threshold's delay."""

from __future__ import annotations

from ..base import FAULT_DURATION, FAULT_START, V_FAULT


def _response(cons, fault_duration_s, fault_voltage_pu):
    if fault_voltage_pu <= cons["VUV"] and fault_duration_s >= cons["TUV"]:
        trip_type, delay = "undervoltage", cons["TUV"]
    elif fault_voltage_pu >= cons["VOV"] and fault_duration_s >= cons["TOV"]:
        trip_type, delay = "overvoltage", cons["TOV"]
    else:
        trip_type, delay = None, None
    fault_end = FAULT_START + fault_duration_s
    sim_end = fault_end + 1.0
    v_points = [(0.0, 1.0), (FAULT_START, 1.0), (FAULT_START, fault_voltage_pu),
                (fault_end, fault_voltage_pu), (fault_end, 1.0), (sim_end, 1.0)]
    if trip_type:
        trip_time = FAULT_START + delay
        p_points = [(0.0, 1.0), (trip_time, 1.0), (trip_time, 0.0), (sim_end, 0.0)]
        markers = {"trip_time": trip_time}
    else:
        p_points = [(0.0, 1.0), (sim_end, 1.0)]
        markers = {}
    return {"v_points": v_points, "p_points": p_points, "sim_end": sim_end,
            "trips": trip_type is not None, "trip_type": trip_type, "markers": markers}


def simulate_step_trip_response(cons, fault_duration_s=FAULT_DURATION, fault_voltage_pu=V_FAULT):
    return _response(cons, fault_duration_s, fault_voltage_pu)


__all__ = [
    "simulate_step_trip_response",
]
