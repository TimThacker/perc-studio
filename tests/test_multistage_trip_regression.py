"""Regression guard: PERC1 always evaluates all 4 stages of its multi-stage
voltage trip table (the vendor manual's "Option 3": VDPA1-3/DMA1-3 and
VDUA1-3/TDUA1-3), not just the single Option-1 trip point (VDPA/DMA, VDUA/TDUA).

Direct PSS/E v35.6.4 simulation against the real compiled PERC2_V35.dll
confirmed this using the two fixtures in
tests/fixtures/multistage_trip/ - identical except for their stage 2-4 values.
These tests pin that finding so the app's own simulator and export path keep
matching it. See docs/developer/PERC1_MODEL.md's "Option 3 is always live" section
for the full write-up.
"""

import os

import pytest

from dev.validation.checks import (
    MULTISTAGE_OVERVOLTAGE_PROBE,
    MULTISTAGE_UNDERVOLTAGE_PROBE,
    evaluate_multistage_probe,
)
from psse.runner import get_runner

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "multistage_trip")


def _run_probes(runner):
    with open(os.path.join(FIXTURE_DIR, "ercot_nogrr282_vendor_default_stages.dyr"), "r", encoding="utf-8") as f:
        vendor_default_dyr = f.read()
    with open(os.path.join(FIXTURE_DIR, "ercot_nogrr282_full_curve_stages.dyr"), "r", encoding="utf-8") as f:
        full_curve_dyr = f.read()

    probes = (MULTISTAGE_UNDERVOLTAGE_PROBE, MULTISTAGE_OVERVOLTAGE_PROBE)
    vendor_default_results = {
        s.id: runner.run(None, vendor_default_dyr, s, block_name="it", case_id="vendor-default-stages") for s in probes
    }
    full_curve_results = {
        s.id: runner.run(None, full_curve_dyr, s, block_name="it", case_id="full-curve-stages") for s in probes
    }
    return vendor_default_results, full_curve_results


def test_mock_runner_reproduces_the_psse_confirmed_multistage_finding():
    """Always runs (no real PsseRunner needed): since reporting.
    simulate_perc1_response now evaluates all 4 Option-3 stages the same way
    the real DLL does, MockPsseRunner - which delegates to it - independently
    reproduces the exact conclusion the real PSS/E validation reached
    on these exact fixtures: stages_live is True.
    This is real cross-validation, not a tautology - it would fail if the
    mock's stage-evaluation logic ever diverged from what actually happens in
    PSS/E, since both are checked against the same two independently-authored
    .dyr fixtures."""
    runner = get_runner("mock")
    vendor_default_results, full_curve_results = _run_probes(runner)
    verdict = evaluate_multistage_probe(vendor_default_results, full_curve_results)
    assert verdict.stages_live is True, verdict.explanation


def _real_runner_available() -> bool:
    try:
        get_runner("psse")
    except NotImplementedError:
        return False
    return True


@pytest.mark.skipif(
    not _real_runner_available(), reason="no PSS/E selected: set PERC_STUDIO_PSSE_VERSION (and PERC_STUDIO_PSSE_DLLS); see src/dev/cli/README.md"
)
def test_multistage_stages_are_confirmed_live():
    """Once a real (psspy-backed) PsseRunner exists, running the same two
    fixtures/probes through it must reproduce the same confirmed finding as
    both the original standalone PSS/E validation and the mock runner above:
    Option 3's stages are LIVE. If this ever asserts stages_live is False
    instead, either the DLL's behavior changed or this PsseRunner disagrees
    with the standalone validation - investigate, don't just flip the
    assertion back."""
    runner = get_runner("psse")
    vendor_default_results, full_curve_results = _run_probes(runner)
    verdict = evaluate_multistage_probe(vendor_default_results, full_curve_results)
    assert verdict.stages_live is True, verdict.explanation
