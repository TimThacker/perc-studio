# What the black-box boundary search cannot see

Black-box validation ([BLACK_BOX_VALIDATION.md](BLACK_BOX_VALIDATION.md)) characterizes a load model by searching, for
each sag depth, swell level or held frequency, for the longest disturbance the load **rides through**
(`search.BoundarySearch`, section 5.7). The outcome of every run is reduced to one bit - *good* (rode through or
momentary cessation) or *not* - and the search bisects where that bit flips.

That is the right question for "does this model meet a ride-through standard?", and it is efficient. It is the wrong
question for several behaviors that newer load models have and that a planner cares about. PSS/E's PERC2 model
(`PERCxx2U`, [PERC2 standard model page](../user/model_perc2_standard.md)) has all of them, so this document works
through each one with a PERC2 record whose true behavior is known from the PERC2 validation library (not published), runs that record
through the app's own black-box validation on PSS/E 36.7.1, and compares.

## The demonstration record

A record written by the app's PERC2 exporter:

| Check | Setting | True behavior (from the PERC2 library) |
|---|---|---|
| momentary low | `Vtf < 0.5` pu for 0.1 s | ceases; reconnects 0.3 s after recovery, 1 s ramp |
| long low | 0.9 pu / 3 s, 0.8 pu / 1.5 s, 0.45 pu / 0.5 s (point 3 off) | ceases; reconnects **5 s** after recovery, **10 s** ramp |
| long high | 1.1 pu / 2 s, 1.15 pu / 1 s, 1.2 pu / 0.25 s | ceases; reconnects 3 s after recovery, 5 s ramp |
| frequency | below 58 Hz or above 62 Hz for 1 s | ceases **for good** |
| reconnect window | 0.7 < Vtf < 1.08 pu | a sag between 0.7 and 0.9 pu lasting longer than its long point **cycles** |
| fractions | fcease 1, frecon 1; droop 0 | |

So the true undervoltage picture has **two** boundaries at each depth below 0.5 pu - the momentary cease at 0.1 s and the
escalation to a long cease at 0.5 s, which changes the reconnect time from 1.3 s to 15 s - and a third, permanent
outcome for frequency.

## What the black-box run reported

`perc-studio blackbox --psse-version 36.7 --level standard --preset ercot_nogrr282` on the demonstration record: 442 PSS/E
cases in 25 minutes, all solved except an exact 0 pu bus held 0.24 s or longer (PERC2 returns NaN there).

**What it got right.** The undervoltage curve is the first cease at every depth: 0.11-0.19 s for 0-0.4 pu (`Tcease` 0.1 s
plus the filter), 1.48-1.52 s for 0.6-0.7 pu (`VLC2`), and later than the setting at depths that sit exactly on a
threshold (0.5, 0.8, 0.9 pu: the strict-comparison knife edge). Overvoltage 1.15-1.3 pu and frequency 57-58, 62 Hz cease
where the CONs say. The ERCOT comparison ("fails" below 0.5 pu and at 1.2 pu) is right for this record.

**What it could not say** - every row below is from the run's own case outcomes:

| Event | What the run recorded | Truth | Limit |
|---|---|---|---|
| 0.3 pu for 0.16-0.41 s | tripped, reconnected after 0.38 s, 0.97 s ramp | momentary cease, `Trecon` 0.3 s, ramp 1 s | (correct) |
| 0.3 pu for 0.58 s or longer | **tripped, did not reconnect** | escalated to a long cease at 0.5 s; reconnects after 5 s with a 10 s ramp, beyond the observation window | L1, L5 |
| the 0.41-0.58 s change of class at 0.3 pu (and at every depth below 0.45 pu) | not searched: both sides are "not good" | the escalation boundary, `TVLC4` 0.5 s | L1 |
| reconnection family | one trip event (0.9 pu, 3.49 s); **reconnect window 0.90-1.08 pu**, delay 5.17 s, ramp 9.6 s | window **0.70**-1.08 pu: a recovery to 0.8-0.89 pu reconnects, then ceases again on the long point (it cycles), so it looks like no reconnection; the momentary reconnect (0.3 s + 1 s) is never measured | L2, L3 |
| 1.25 pu, 57 Hz, 62 Hz | tripped, did not reconnect (all three) | the swell reconnects after 3 s + 5 s; the frequency ceases never do | L5 |
| repeated sags (0.1 and 0.9 pu) | no change with the gap | the ramp can be interrupted; never exercised | L4 |
| initialization | steady, drift 0.002 % | (correct here: `Ldfact` 0.8 <= `Ipmax`) | L8 would pass a load that starts 17 % low |

The tolerance curve and the preset verdicts are right. The reconnect behavior - which is what the PERC2 model adds - is
reported for one event, with the wrong lower voltage, and every other reconnect is either missing or labelled as never.


## The PERC2 DLL v2.3 demonstration

The same exercise with ISO-NE's PERC2 v2.3 DLL, a user model the app now also writes
([PERC2 DLL model page](../user/model_perc2_dll.md)), run on **both** PSS/E 35.6.4 (`PERC2_v35_v2p3.dll`) and
36.7.1 (`PERC2_v36_v2p3.dll`): Standard level, ERCOT NOGRR282, 394 cases each, about 40 minutes each. The record
(written by the app's exporter) turns momentary cessation on and returns the load to 80 % after every cease (FRECON 0.8):

| Check | Setting | True behavior (from the v2.3 library) |
|---|---|---|
| momentary cessation | below 0.5 / above 1.15 pu, at once | back after 0.15 s inside 0.8-1.08 pu, 1 s ramp, to 80 % |
| low stages | 0.9 pu / 3 s, 0.8 / 1.5 s, 0.5 / 0.5 s | back 5 s after V > 0.85 pu, 10 s ramp, to 80 %; a cessation that outlasts the 0.5 s stage becomes this trip |
| high stages | 1.1 pu / 2 s, 1.2 / 0.25 s | back 3 s after V < 1.08 pu, 5 s ramp |
| frequency | 58 / 62 Hz for 1 s | back 5 s after 58.5-61.5 Hz, 5 s ramp |
| PSS/E 36.7 only | the v36 build | the process exits at the end of every high-side cessation ramp |

**What it got right.** Both versions report the same curve, and it is right where a boundary is a single stage:
1.48-1.52 s at 0.6-0.7 pu (the 0.8 pu / 1.5 s stage), 3.13-3.21 s at 0.9 pu, 2.01-2.06 s at 1.15 pu (1.1 pu / 2 s),
1.02-1.05 s at 57 Hz; the momentary cessation's own boundary - the time the filtered voltage takes to cross VLBLK or
VUBLK - at 0.021-0.037 s for 0.2-0.4 pu and 0.029-0.030 s at 1.2 pu; the upper edge of the stage reconnect window
(1.0775-1.081 pu, VRUPA 1.08); and the `run()`-cadence sensitivity of the ramp, which the report states.

**What it could not say:**

| Event | What the run recorded | Truth | Limit |
|---|---|---|---|
| 0.3 pu for 0.03-0.4 s | **tripped, did not reconnect** (final level 0.80) | momentary cessation, back after 0.15 s + 1 s ramp, to 80 % | **L11**, **L12** |
| 0.0 and 0.1 pu, any duration | never rides through; the preset comparison "not solvable" at 0 pu | cessation within one cycle, as at 0.3 pu (0 pu: the rig, see L9-L10 notes) | L11, L12 |
| 0.3 pu for 0.5 s or longer | the same "tripped, did not reconnect" as at 0.1 s | escalated to the 0.5 pu stage trip: back after 5 s + 10 s instead of 0.15 s + 1 s | L1, L5 |
| reconnection family | one trip event (0.9 pu, 3.2 s); **window 0.90-1.08 pu** | window **0.85**-1.08 pu: 0.85-0.89 reconnects and trips again on the 0.9 pu / 3 s stage (cycling); the cessation band 0.8-1.08 is never measured | L2, L3 |
| 1.2-1.3 pu on 36.7 | 13 cases **"numerical failure"**; the comparison says overvoltage "not solvable"; the diagnosis list is **empty** | the PSS/E process exited (code 66, a Fortran runtime error in the DLL) at the end of the cessation ramp - a defect, not a network that does not solve | **L13** |
| 1.2-1.3 pu on 35.6 | tripped, did not reconnect | cessation, back to 80 % after 0.15 s + 1 s | L11, L12 |
| frequency 57-58, 62-63 Hz | tripped, did not reconnect | back after 5 s + 5 s, to 80 % | L5, L11 |

The tolerance curve is right; the reconnect behavior - most of what this record does - is reported as "did not
reconnect" at every depth, and the one defect that loses a whole study on PSS/E 36 is reported as a numerical failure.
Because the search only asks "good or not", the curve itself is identical on the two versions: the crash changes only
the label of points that were "not good" anyway.

## The limits, one by one

| # | Behavior | What the search does with it | Visible in the report? |
|---|---|---|---|
| L1 | **Several cease levels with different reconnect times** (momentary vs long; PERC1 DLL stages with per-direction reconnect) | Every cease is "not good", so the search stops at the first boundary. Where a longer disturbance escalates to a slower reconnect (0.5 s here) is never searched. | No: one bracket per depth |
| L2 | **Reconnect time depends on the event** | The reconnection family uses one trip event (the shallowest depth that tripped, at its shortest tripping duration) and reports one delay and ramp. | One of the two (or three) |
| L3 | **Cycling during a long event** | The classifier judges what happens *after* the disturbance ends; a load that ceases, reconnects and ceases again during a 20 s sag is "tripped, reconnected". | No |
| L4 | **A disturbance during the reconnect timer or the ramp** | The repeated-sags family uses two sags each short enough to ride through alone, so no second event ever meets a ceased or ramping load. Whether the ramp can be interrupted (the PERC2 sheet says no; PSS/E says yes) is never tested. | No |
| L5 | **A permanent cease** (PERC2 frequency) vs a slow reconnect | Outside the reconnection family the observation window is a few seconds, so "never" and "after 100 s" look the same; the frequency family only asks "rode through?" | No |
| L6 | **Behavior that depends on two quantities at once** (PERC2's 0.7 pu frequency gate: no droop and no frequency cease while the voltage is low) | One disturbance at a time (section 5.10). | No |
| L7 | **Network effects** (bus-frequency spikes when a fault clears) | The playback rig imposes frequency; a computed one never reaches the model. | No |
| L8 | **A load that starts below its power flow** (PERC2 with `Ldfact > Ipmax`: 83 MW for a 100 MW load from the first sample) | The initialization stage checks drift against the run's own first sample, so a load that is wrong from t = 0 is "steady". | No |
| L9 | **A narrow trip window between interior checks** | Already documented (section 5.7, "What it can miss"). | Sometimes |
| L11 | **A partial reconnect** (FRECON < 1: the load comes back to a lower level, as PERC2 v2.3 does after every cease) | Outside the reconnection family a final level below 90 % of the pre-event power (`RECOVERED_FRACTION`) is "did not reconnect"; the reconnect delay and ramp are not recorded at all | No: "tripped, did not reconnect" |
| L12 | **Momentary cessation below 0.5 pu** | The classifier calls a cease momentary cessation only while V is still at or above 0.5 pu when P falls, and P is back to 90 % of its pre-event value within the prompt window (`classify.py`); a model whose cessation threshold is 0.5 pu (VLBLK) or that returns to FRECON is classified as tripping | No |
| L13 | **A model that kills the PSS/E process** | A case whose worker dies is "crashed" and classified "numerical failure", the same class as a network solution failure; the diagnosis does not mention it | Only as "not solvable" |
| L10 | **A defect that shifts one stage** (PERC2 point 3 using point 1's time) | Seen correctly *if* a grid depth falls between that point's voltage and the next one; the measured curve is what PSS/E does. The search cannot say the stage is wrong - only the curve is reported. | Yes, as a measured curve |

## Proposed changes

In order of value for the cost:

1. **Search on the outcome *class*, not one bit (L1, L2).** Let `BoundarySearch` take a key - e.g. (rode through /
   ceased-reconnected / ceased-not-reconnected, reconnect delay rounded to the classifier's resolution) - and bisect
   wherever the key changes, not only where "good" changes. On the demonstration record this adds the 0.5 s escalation
   boundary at each depth below 0.5 pu for about 6 runs per depth. The tolerance curve then shows several boundaries per
   depth, each labelled with its reconnect time.
2. **Size the observation window from what the model does (L2, L5).** After the reconnection family, re-run each class
   boundary's slow side with a window of 1.5 x the longest reconnect seen + 10 s, and add one long hold (e.g. 600 s) per
   class that never reconnected, so "permanent" is measured, not assumed.
3. **A "second event" family (L4).** Trip the load, then apply a second sag at fixed fractions of the measured reconnect
   delay and ramp (25 %, 75 % of each); classify whether the load ceases again, and from what level. Six runs per trip
   class.
4. **A "sustained event" family (L3).** Hold each sag depth for max(3 x the longest reconnect, 60 s) and count ceases
   during the event (P drops of more than half the pre-event power after a recovery). One run per depth; flag "cycles"
   in the report.
5. **Initialization against the power flow (L8).** Compare P and Q at t = 0 with the rig's load MW/Mvar and warn above
   1 %, stop above 10 %, as for drift.
6. **Combined events (L6), optional.** A frequency hold at two depressed voltages (0.6 and 0.75 pu) per held frequency
   at the Full level only.
7. **A network rig (L7), optional.** The PERC2 library's `smib` rig (a classical machine behind a line, a bus fault) is
   enough to show computed bus-frequency excursions; as a Full-level option it would catch frequency logic that fires
   on fault clearing.

8. **Classify a partial return (L11, L12).** Record the reconnect delay, ramp and final level whenever P climbs back,
   whatever the final level, and class it "ceased, partial reconnect" in every family (the reconnection family already
   has `trip_partial_reconnect`). Recognize momentary cessation by its timing (cease within a cycle or two of the
   disturbance, back within a short window after it), not by the voltage staying above 0.5 pu or the return being full.
9. **Report a dead process as a crash (L13).** Keep `crashed` as its own class, show it in the curve and the comparison
   as "PSS/E stopped", and add a diagnosis row that names the cases and the exit code, with the hint to run one case by
   hand to see the runtime's message (a Fortran runtime error goes to the console, not to PSS/E's report).

Items 1, 2, 5 and 8 change the core (8 is the classifier, 9 the report); 3 and 4 are new families in `families.py` and `protocol.py` with the same
`run_searches` batching; 6 and 7 are optional levels. None of them changes a CON - the method stays black-box.
