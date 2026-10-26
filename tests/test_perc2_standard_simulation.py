"""The analytic simulator of the PERC2 standard model. Its match to PSS/E 36.7.1 traces was checked against the
PSS/E validation library, which is not published; these tests pin the behavior that does not need those traces."""


import pytest

from load_models.perc2_standard import MODEL
from load_models.perc2_standard.cons import DEFAULT_CONS
from presets.ridethrough import RIDE_THROUGH_PRESETS


def test_frequency_cease_is_reported_as_permanent():
    cons = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")
    out = MODEL.simulate_frequency(cons, 150.0, 57.5)
    assert out["trips"] and out["trip_type"] == "underfrequency" and out["never_reconnects"]
    assert "reconnect_start" not in out["markers"] and out["stays_tripped_reason"]


def test_overvoltage_cease_uses_the_long_high_reconnect():
    cons = MODEL.cons_for_preset(RIDE_THROUGH_PRESETS["ercot_nogrr282"], "it")
    out = MODEL.simulate(cons, 0.3, 1.25)
    m = out["markers"]
    assert out["trip_type"] == "overvoltage" and out["cease_check"] == "VHC2"
    assert m["reconnect_end"] - m["reconnect_start"] == pytest.approx(cons["TLrampH"] * cons["Ldfact"], abs=0.01)


def test_cycling_is_reported_with_every_round():
    cons = {**DEFAULT_CONS, "VLLflag": 1, "VLC1": 0.9, "TVLC1": 1.5, "VLC2": 0.0, "VLC4": 0.0, "TLreconL": 1.0,
            "TLrampL": 3.0, "VLrecon": 0.7, "VLMflag": 0}
    out = MODEL.simulate(cons, 10.0, 0.85)
    assert out["cycles"] and len(out["trip_events"]) >= 3 and len(out["reconnect_events"]) >= 3


def test_a_stranded_reconnect_window_says_why():
    out = MODEL.simulate({**DEFAULT_CONS, "VHcease": 0.95, "VHrecon": 1.1, "Trecon": 0.3}, 0.3, 0.3)
    assert out["trips"] and "excludes" in out["stays_tripped_reason"]
