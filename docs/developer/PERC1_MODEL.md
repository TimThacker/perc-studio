# The PERC1 / CLOD model reference

This is the deep-dive reference for the two PSS/E dynamic models this app
generates - **PERC1** (power-electronics-interfaced load: IT/UPS, VFD-driven
cooling) and **CLOD** (conventional motor-driven cooling load). If you just
want to run the app, see the main [README.md](../../README.md); come here when
you need to know what a specific CON does, why a value is held fixed, or how
a preset becomes a number in the exported `.dyr`.

## The PSS/E PERC1 load model

PERC1 ("Power Electronic Load Model") is a PSS/E user-defined model used to
represent power-electronics-interfaced load (UPS/IT load, VFD-driven cooling,
and similar) in bulk power system dynamic simulations. It is based on an
Electric Vehicle (EV) charging load model jointly developed by EPRI and LBNL,
and is built around two symmetric control loops - one for active power, one
for reactive power - plus a "cease and reconnect" state machine that governs
how the block behaves during and after a voltage disturbance.

**PERC1 has (at least) two distinct PSS/E implementations, and this app
supports both as separate load models:**

| Variant | PSS/E versions | CON layout | Supported by this app? |
|---|---|---|---|
| **DLL** | v34, v35 - developed by ISO New England (ISO/NE) | 173 CONs: four repeated "channel" blocks (A/B/C/D), an Option-3 stepped multi-level voltage trip/reconnect table (4 stages per direction), one frequency trip/reconnect point per direction (the data sheet's stage-2-4 frequency CONs are marked NOT USED). Verified 2026-09-17 directly against a vendor-supplied example `.dyr` record (see `src/load_models/perc1_dll/cons.py`'s module docstring). | **Yes - this is the only variant this app currently generates.** |
| **Standard** | v36.5+ (documented against 36.7) | The model shipped as PSS/E's own built-in standard model (not a separately-loaded DLL): `PERCBL1U`/`PERCOW1U`/`PERCZN1U`/`PERCAR1U`/`PERCAL1U`, `ModelLibrary.pdf` section 13.6. 30 CONs, 8 states, 24 VARs. One undervoltage cease/reconnect cycle plus droop, voltage exponents and current limits; **no** high-voltage or frequency cease/reconnect, momentary cessation or stepped trip table. It is a *component* of PSS/E's composite load: a `MAINxx10` record has to sit above it. | **Backend: yes** - `load_models.perc1_standard` (model id `perc1_standard`): `.dyr` export and parse, validated limits, preset mapping, all checked in PSS/E 36.7.1 (in the PSS/E validation library, which is not published). **Desktop UI: not yet** - the Screening and Post-Commissioning tabs still drive the DLL model only. |

Do not assume the Standard variant shares the DLL variant's CON names,
defaults, or structure - they are different models. Everything below this
point describes the **DLL** variant; the Standard variant has its own
section, "DLL variant vs. the newer Standard PERC1 implementation".

### Model structure

Each power loop (active and reactive) is built from the same chain of blocks:

1. **Washout block** - optional high-pass filter on terminal voltage, used to
   shape the transient response. Bypassed by setting its gain/time constant
   to 0.
2. **Droop** (active power loop only) - makes real power responsive to system
   frequency. Bypassed by setting `DROOPA` to 0.
3. **Lead-lag block** - shapes the transient response further. Bypassed by
   setting both time constants to 0.
4. **ZIP exponent** (`NPA`/`NQA`) - selects whether the block behaves as
   constant power (0), constant current (1), or constant impedance (2) as
   terminal voltage moves away from 1.0 pu.
5. **Current limits** (`IPMAXA`/`IPMINA`/`IQMAXA`/`IQMINA`) - bound the
   per-unit current the block can draw.
6. **Numerical filter** (`TRA`/`Tt`) - a small filter time constant included
   purely to help simulation numerical stability (recommended: ~4x the
   simulation time step).
7. **FracOn cease/reconnect logic** - a state machine that determines what
   fraction of the block's load is "on" at any instant, based on measured
   terminal voltage (and, for the frequency-protection CONs, system
   frequency).

The vendor UDM ships three alternative ways to drive that last block. All
three are documented in the vendor's own PERC1 DLL documentation, verified
directly against this app's layout on 2026-09-17:

| Option | What it represents | Used by this app? |
|---|---|---|
| **1 - Undervoltage cease/reconnect** | A single trip voltage/delay and a single reconnect voltage/delay/ramp - the load fully or partially "ceases" below a threshold and ramps back in after voltage recovers. | **Yes** - every preset and the default parameters drive this. |
| **2 - Momentary cessation** | The block rides through a brief sag/swell window (`VLBLK`/`VUBLK`) and resumes after a fixed delay, independent of a discrete trip/reconnect voltage. | No - CONs are present in every exported record at documented standard values, but the app does not ask about this and does not enable it (`ICON(M+1)=0`). |
| **3 - Stepped multi-level trip/reconnect** | A 4-stage voltage ride-through/reconnect table (undervoltage *and* overvoltage) plus one frequency trip/reconnect point per direction, for facilities with staged protection settings. | **Voltage side: yes, as of 2026-09-24** - every preset (and the single-point default parameters) now populates the full 4-stage table; see ["Option 3 is always live"](#option-3-is-always-live) below. **Frequency side: yes, for presets with a published frequency table** (PJM LCL, NERC PRC-029-1); the DLL trips on it, on time - confirmed in PSS/E 2026-09-25. |

Per the vendor's own documentation: *"The Option 2 and 3 are not yet
officially part of the NERC LMWG endorsed PERC1 model. These requirements
and their implementation are key topics for the next set of model
buildouts."* That describes the vendor's own *endorsement* status, not the
compiled DLL's actual runtime behavior - direct PSS/E simulation (see below)
confirmed the DLL evaluates Option 3's voltage stages unconditionally,
regardless of endorsement status or facility intent.

**The gap this section used to describe is closed.** Option 1 accepts
exactly one undervoltage trip point and one overvoltage trip point - a
single "below this voltage, hold this long, then trip" rule - but the
grid-operator standards this app parameterizes against (ERCOT, SPP, PJM,
MISO, both NERC entries) each publish a multi-row performance table, not a
single point. This app's own preset library now reproduces that full table
via `multi_stage_undervoltage()`/`multi_stage_overvoltage()` in
`src/presets/ridethrough.py`, feeding Option 3's real stage CONs (`VDPA1-3`/
`DMA1-3`, `VDUA1-3`/`TDUA1-3`) - not a conservative approximation of it. See
[`docs/user/presets/README.md`](../user/presets/README.md#how-a-multi-tier-standard-becomes-a-full-multi-stage-psse-con-table)
for exactly how it works and a worked example.

### What's in the DLL variant's 173 CONs that this app doesn't drive

This app only ever varies Option 1's channel-A CONs per facility. Everything
else in the 173-CON layout (`src/load_models/perc1_dll/cons.py`'s `PERC1_DYR_LAYOUT`) is
still written to every `.dyr` record - PSS/E requires the full CON array
regardless - just held at a fixed, vendor-typical value. For anyone reading
a generated `.dyr` file who wonders what the rest of it is:

- **Channels B, C, and D.** The DLL variant's `.dyr` layout repeats the same
  22-CON block four times (`VDPA`/`DMA`/`TDRA`/`VRPA`/`RAMPA`/`DROOPA`/
  `KWASHA`/`TWASHA`/`TA`/`TB`/`FRA`/`NPA`/`VNOMA`/`IPMAXA`/`IPMINA`/
  `IQMAXA`/`IQMINA`/`TRA`/`NQA`/`DBA`/`VDUA`/`TDUA` for channel A, then the
  same 22 fields again with a `B`/`C`/`D` suffix) plus a matching `VRUPB`/
  `TRUPB`/`RAMPUB` (etc.) reconnect block per channel. This app only ever
  populates channel A and holds B/C/D entirely at `0.0` (the vendor's own
  documentation marks every B/C/D field "NOT USED", except `FRB`/`FRC`/`FRD`
  which it explicitly requires to be `0`, not merely "don't care") - the
  vendor spec supports representing up to four independently-parameterized
  load fractions within one PERC1 instance, but this app instead represents
  each load block as its own separate PERC1 model instance -
  `build_perc1_dyr_block` is called once per block (IT, VFD) with a distinct
  load ID, each writing its own complete 173-CON record - so the
  multi-channel feature is simply never exercised.
- **`ZETAA`/`WNAA`/`ZETAB`/`WNAB`/`ZETAC`/`WNAC`/`ZETAD`/`WNAD`.** A
  damping-ratio/natural-frequency pair per channel, marked "NOT USED" for
  all four channels (including A) in the vendor's own documentation - held
  at `0.0`.
- **Option 2 - momentary cessation (`VLBLK`/`VUBLK`/`TBLK`/`TDELY`).** An
  alternative to Option 1 where the block rides through any sag/swell that
  stays within a `VLBLK`-`VUBLK` window and simply resumes after a fixed
  `TBLK`/`TDELY` delay, with no discrete trip/reconnect voltage at all.
  Held at vendor-typical values (`VLBLK=0.5`, `VUBLK=1.1`, `TBLK=0.0167`,
  `TDELY=0.033`, confirmed identical across two independent vendor
  examples) but never activated - `ICON(M+1)` (the flag selecting momentary
  cessation) is always written as `0` by this app.
- **Option 3 - stepped multi-level trip/reconnect - now driven, voltage side.**
  A **4-stage** voltage ride-through table for each direction, not 3: the
  vendor's own documentation is explicit that `VDPA`/`DMA` (Option 1's own
  point, at CON `J`/`J+1`) is itself the *first* of four stages, with
  `VDPA1`/`DMA1`, `VDPA2`/`DMA2`, `VDPA3`/`DMA3` (CONs `J+96`-`J+101`) as
  the 2nd-4th - its own data sheet literally labels them "SECOND", "THIRD",
  "FOURTH" low-voltage setpoints, drawn in the vendor's own diagram as one
  continuous staircase, not two separate tables. Same structure on the high
  side: `VDUA`/`TDUA` (CON `J+20`/`J+21`) plus `VDUA1..3`/`TDUA1..3` (CONs
  `J+102`-`J+107`). Reconnect after a high-voltage trip uses its own
  `VRUPA`/`TRUPA`/`RAMPUA` (CONs `J+108`-`J+110`), separate from
  `VRPA`/`TDRA`/`RAMPA`.

  #### Option 3 is always live

  **Resolved 2026-09-24, via direct PSS/E v35.6.4 simulation against the real
  compiled `PERC2_V35.dll`** (not inferred from the vendor documentation,
  which describes no flag either way): **the compiled DLL always
  evaluates all 4 undervoltage and all 4 overvoltage stages, unconditionally,
  for every facility.** There is no "Option 1 only" mode - unlike Option 2
  (explicitly gated by `ICON(M+1)`), nothing disables stages 2-4. Three
  independent PSS/E probes confirmed this (in the PSS/E validation library, which is not published):

  1. **Undervoltage** - a sag to 0.75pu held 0.6s tripped at t=1.06s (fault
     at t=0.5s), with voltage crossing `VDPA1=0.80pu` around t=0.53s - an
     observed ~0.53s dwell against a configured `DMA1=0.50s`.
     ([plot](../user/figures/perc1dll_multistage_undervoltage.png))
  2. **Overvoltage (the headline result)** - with voltage sustained above
     `VDUA=1.20pu` for 500ms+, a fixture with `TDUA1-3=0.0s` tripped in
     ~20-30ms while an otherwise-identical fixture with `TDUA1-3=2.0s` rode
     through the identical excursion with no trip - both fixtures share the
     exact same `VDUA=1.20pu`/`TDUA=2.0s` Option-1 point, so the only thing
     that could explain the different outcome is the untouched Option-3
     stage.
  3. **Stage-2 dwell-time precision** - two fixtures differing *only* in
     `DMA2` by 0.10s (0.15s vs. 0.25s) produced trip times differing by
     exactly 0.10s (0.73s vs. 0.83s) - proof the DLL honors each stage's
     configured dwell time quantitatively, not just qualitatively.

  **Consequence and fix, both now implemented:** before this date, every
  `.dyr` this app exported left `VDPA1-3`/`DMA1-3`/`VDUA1-3`/`TDUA1-3` at
  the vendor's own worked-example values (real, non-degenerate breakpoints,
  not inert sentinels - `(0.80, 0.50)`/`(0.5, 0.15)`/`(0.5, 0.15)`
  undervoltage; `VDUA1..3=1.2`/`TDUA1..3=0.0` overvoltage), so every facility
  silently carried this extra, unintended, preset-independent trip condition
  regardless of its own real `VDPA`/`DMA`/`VDUA`/`TDUA`. This is fixed:
  `load_models.perc1_dll.cons.voltage_stage_cons()` is the single function that writes all 8
  stage CONs, and every params-building path in this app now calls it -
  `presets/ridethrough.py`'s preset bundles populate the real 4-stage table
  from that standard's own published envelope (see
  [`docs/user/presets/README.md`](../user/presets/README.md#how-a-multi-tier-standard-becomes-a-full-multi-stage-psse-con-table)),
  and the model's default parameters (`PERC1_DEFAULT_CONS`) repeat their
  one point into every stage instead - a repeated stage fires at the exact
  same time as the tier it copies, so it cannot introduce a different,
  earlier trip (this exact pattern is what probe 3 above validates). The 12 stage CONs are also now
  directly editable in each block's **Voltage ride-through** parameter row,
  in its "Undervoltage trip stages"/"Overvoltage trip stages" sections
  (`editor.model_ui.PERC1_FIELD_GROUPS`) - not a separate row from stage 1's own
  `VDPA`/`DMA`/`VDUA`/`TDUA`, since there is no "off" state for stages 2-4 to
  make a separate group's existence imply; the under/over split is purely
  organizational, to make each direction's own 4 stages easy to find and
  compare. The live-preview chart's panel 3 ("Trip
  threshold vs. ride-through envelope") plots all 4 stages per direction as
  independent points, each checked against the selected preset's envelope at
  its own duration - editing a stage's own CON moves only that stage's own
  point (`preview.perc1_dll.build_perc1_response_figure`).

  **Update, 2026-09-25 - overvoltage stages model the published tier's own
  "or trip" language literally, with no invented breakpoints, and stage 1
  now arms at the continuous ceiling rather than the published tier's own
  voltage.** Every standard in this library publishes at most one real
  mandatory overvoltage tier, and the ones that address the question at all
  say the same thing ERCOT NOGRR282 does explicitly: "above 1.20 pu: may
  ride through or trip." That silence beyond the tier is modeled directly:
  stages 2-4 repeat the *same voltage* as the real published tier (never a
  higher, app-invented one) with `TDUA1-3=0.0s` - trip essentially
  immediately above it. An earlier version of this fix instead invented
  three graduated breakpoints above the published tier
  (`OVERVOLTAGE_SEVERE_SWELL_OFFSETS` at +0.10/+0.30/+0.60 pu); that was
  corrected per explicit review feedback, since it assumed relay-curve
  behavior no standard in this library actually publishes.

  A second correction followed immediately after: ERCOT's own row - "up to
  1.20 pu: must tolerate for at least 2.0 s" - describes the whole *band*
  above the continuous ceiling (1.10 pu), not a threshold that only starts
  mattering once V reaches 1.20 pu. A swell held at 1.15 pu must be able to
  trip after 2.0 s too, the same as one held at 1.20 pu - it cannot ride
  through indefinitely. Since `VDUA`/`TDUA` is a simple "trip if V exceeds
  VDUA for TDUA seconds" timer, reproducing that band means **stage 1 now
  arms at the continuous ceiling's own voltage (1.10 pu), not the published
  tier's own upper voltage (1.20 pu)**, keeping that tier's own duration
  (2.0 s). Both 1.10 and 1.20 are ERCOT's own published setpoints - no new
  voltage is invented, only which of the two already-listed setpoints
  stage 1 arms at.

  This reuses the exact same per-stage independent-timer mechanism Q1
  validated in PSS/E - only the arming voltage changed, not the mechanism -
  and stages 2-4 (`VDUA1-3=1.20`/`TDUA1-3=0.0`) are in fact exactly what the
  very first overvoltage probe's fixture already used
  (`tests/fixtures/multistage_trip/ercot_nogrr282_vendor_default_stages.dyr`, confirmed to trip in
  ~20-30ms - see plot 2 above), so that half of this is a return to an
  already-validated default, not a new, unvalidated one.
  See [`docs/user/presets/README.md`](../user/presets/README.md#how-a-multi-tier-standard-becomes-a-full-multi-stage-psse-con-table)
  for the full explanation and every preset's own resulting numbers.

  The time-domain
  simulation itself (panels 1-2, voltage(t)/power(t) - and the
  `MockPsseRunner` CLI/sweep path, which delegates to the same function)
  evaluates all 4 stages too, not just stage 1:
  `load_models.perc1_dll.simulation.simulate_perc1_response` treats every stage the fault's depth
  crosses as an independently-timed trip condition counting down from the
  same fault onset, exactly mirroring the real DLL's independent per-stage
  timers confirmed above, so a preset whose stage 2 has a shorter dwell than
  stage 1 (e.g. ERCOT NOGRR282's `DMA1=0.50s` vs. `DMA=2.00s`) now correctly
  shows that earlier trip in the simulated response, not just in panel 3's
  static comparison.
- **Frequency ride-through - one trip/reconnect point per direction
  (`FOFTP1`/`TOFTP1`/`FOFRN1`/`TOFRN1`/`ROFRN1` and
  `FUFTP1`/`TUFTP1`/`FUFRN1`/`TUFRN1`/`RUFRN1`) - driven per preset where a
  standard publishes a table; confirmed live in PSS/E (2026-09-25).**
  The record carries four suffixed frequency sets (`1`-`4`), but the vendor
  documentation (Data_Center_Performance_Model_PERC1_PSSEV34_V35_documentation_Rev7.pdf) is explicit that only the first is used: "CONs
  J+120 to J+129 are for frequency tripping and reconnection", and its data
  sheet marks every stage-2-4 frequency CON (J+130 to J+159) **NOT USED**.
  (Voltage is different: its stages 2-4 are named "SECOND"/"THIRD"/"FOURTH"
  setpoints and are live.) The vendor example sets stage 1 to trip above
  62.0 Hz or below 58.0 Hz after 100 s and fills the unused sets with
  99 Hz / 999 s.

  **How the app drives it.** Presets whose source publishes a complete
  frequency table - PJM's LCL proposal and NERC PRC-029-1 (Attachment 2,
  Table 3: continuous 58.8-61.2 Hz, 299 s down to 57.0 Hz / up to 61.8 Hz,
  may trip beyond) - carry it as `RideThroughPreset.frequency_ride_through`,
  and `presets.ridethrough.frequency_trip_points()` collapses it to the one
  point per direction the model holds: arm at the continuous band's edge
  with the innermost row's duration (below 58.8 Hz / above 61.2 Hz after
  299 s). That never trips where the table requires riding through; it
  rides through longer than required beyond 57.0/61.8 Hz, which is always
  compliant. Reconnect frequency is the continuous band's edge; reconnect
  delay/ramp keep the vendor's 100 s / 5 s. Every other preset - and the
  default parameters - keep the vendor values.

  With one trip point per direction, the block's frequency behavior is a
  **deadband**: it rides through indefinitely between `FUFTP1` and `FOFTP1`
  and trips once frequency has stayed outside that band for
  `TUFTP1`/`TOFTP1`. The app presents it that way - the **Frequency ride-through**
  parameter row has a "Frequency deadband" section (low and high edges), a
  "Trip delays" section, and the two reconnect sections, and choosing
  "Frequency event" opens that row;
  the live chart's frequency panel shades the band and dashes the trip
  region beyond each delay.

  The live chart simulates frequency events (the "Frequency event" toggle):
  `simulate_perc1_frequency_response()` evaluates the stage-1 trip point per
  direction on the `TFRQ`-filtered frequency, applies `FCEASE`/`FRECON` to a
  frequency trip, and applies `DROOPA` droop while the block is online (all
  confirmed in PSS/E; see [Measured runtime behavior](#measured-runtime-behavior)).

  A separate PSS/E test (a real generation/load imbalance, not an imposed
  signal - system frequency is a genuine swing-equation state) confirmed
  `DROOPA` (frequency droop on the active-power loop) is live: the block's
  real power output declined smoothly and substantially in direct response
  to an induced frequency decline
  ([plot](../user/figures/behavior_droop.png)).

  **Update, 2026-09-25 - measured in PSS/E with the preset validation library
  (not published).**
  - The frequency trip point trips in both directions, at its delay
    +0.083 s. The stage-2-4 frequency CONs are ignored even when armed.
  - Droop is P = 1 + `DROOPA`·Δf/60: −25% at 58.5 Hz for every preset's
    `DROOPA=10`. `DBA` is a deadband on it, in Hz. The app's frequency
    simulator applies it (full rule in
    [Measured runtime behavior](#measured-runtime-behavior)).

None of the above is deprecated or broken - it's real vendor-specified DLL
variant structure. The voltage side is fully driven per facility; the
frequency side is driven for presets with a published frequency table and
editable for any facility, and the compiled DLL trips on it as documented
(see the update above).

### Which reconnect settings apply to which trip

PERC1 does **not** have one shared set of reconnect settings. Per the vendor
documentation, each trip path reconnects through its own CONs:

| Trip path | Trip CONs | Reconnect point | Reconnect delay | Reconnect ramp | Scope |
|---|---|---|---|---|---|
| Undervoltage | `VDPA`/`DMA`, `VDPA1-3`/`DMA1-3` | `VRPA` | `TDRA` | `RAMPA` | One set for all 4 stages |
| Overvoltage | `VDUA`/`TDUA`, `VDUA1-3`/`TDUA1-3` | `VRUPA` | `TRUPA` | `RAMPUA` | One set for all 4 stages ("mirrors VRPA/TDRA/RAMPA for the high side") |
| Under-frequency | `FUFTP1`/`TUFTP1` | `FUFRN1` | `TUFRN1` | `RUFRN1` | One point (stages 2-4 NOT USED) |
| Over-frequency | `FOFTP1`/`TOFTP1` | `FOFRN1` | `TOFRN1` | `ROFRN1` | One point (stages 2-4 NOT USED) |

`FCEASE` (fraction that trips) and `FRECON` (fraction of that which
reconnects) are the only settings documented as shared - and the vendor
text describes them only on the voltage cease/reconnect path.

**There is no fallback to a "general" value.** The exported `PERCBL` record
always writes all 173 CONs, so no reconnect setting is ever "unset", and the
vendor documentation describes no rule by which the frequency reconnect CONs
(or `VRUPA`/`TRUPA`/`RAMPUA`) defer to `VRPA`/`TDRA`/`RAMPA`. Whatever value a
CON holds is, per the documentation, the value that path uses. (The
frequency stage-2-4 CONs, which hold 99 Hz / 999 s in the vendor example, are
marked NOT USED, so they are not part of any trip or reconnect path.)

How this app sets them:

- **`VRPA`/`TDRA`/`RAMPA`**: the model's defaults, or a preset's
  published recovery window (see
  [presets/README.md](../user/presets/README.md#trip-fraction-reconnect-fraction-and-reconnect-timing-fceasefrecontdrarampa)).
- **`VRUPA`/`TRUPA`/`RAMPUA`**: always the vendor-typical 1.05 pu / 5 s / 5 s -
  no preset sets them yet. If the DLL uses them as documented, every preset's
  overvoltage recovery is ~10 s, slower than every published 1-2 s recovery
  window; mirroring each preset's `TDRA`/`RAMPA` into them is the likely fix.
  PSS/E confirms the DLL uses them: reconnect ~5.05 s after recovery, then a
  5 s ramp. Editable in the Voltage ride-through row's "Overvoltage reconnect" section.
- **`FUFRN1`/`TUFRN1`/`RUFRN1` and `FOFRN1`/`TOFRN1`/`ROFRN1`**: presets with a
  frequency table reconnect at the continuous band's edge with the vendor's
  100 s / 5 s timing; everything else keeps the vendor values (58.5/61.5 Hz).
  Editable in the Frequency ride-through row's reconnect sections.

The live chart and mock runner follow this table (an overvoltage trip
reconnects on `TRUPA`/`RAMPUA`, a frequency trip on `*FRN1`).
**Confirmed in PSS/E, 2026-09-25.**
Every path uses the CONs in the table, `VRUPA` is a ceiling, and
`FCEASE`/`FRECON` apply to frequency trips too. The table's "reconnect
point" column is really half of a **window**. Both voltage paths reconnect
only while `VRPA` < VFILT < `VRUPA`, and both frequency paths only while
`FUFRN1` < f < `FOFRN1` (see [Measured runtime behavior](#measured-runtime-behavior)).
So `VRPA=1.0` never reconnects unless voltage settles above 1.0 pu, after
an overvoltage trip too. The live chart and mock runner apply the window.

### Measured runtime behavior

Everything below was measured in PSS/E v35.6.4 against the real
`PERC2_V35.dll`. The source is the preset validation library (840 tests)
and the follow-up behavior probes (198 tests; every rule below is checked
against every relevant trace, 744 of 744 checks passing), both part of the
PSS/E validation library, which is not published. None of it is in the
vendor documentation.

**Measurement.**
- VFILT is the terminal voltage through a first-order lag `TVM` (STATE K+7).
- The frequency is PSS/E's own filtered bus frequency (the
  `dynamics_solution_param_2` bus-frequency filter, 0.0333 s by default),
  through a further lag `TFRQ`.

**Trip.**
- Each of the 4 voltage stages per direction times while VFILT is
  **strictly** beyond its threshold, and resets the instant it is not.
  Durations are not cumulative.
- The one frequency point per direction works the same way on filtered
  frequency.
- A trip lands at delay + `CMTDELAY`, plus the filter lag,
  `TVM`·ln((1 − V)/(V_stage − V)), plus one step.
- The frequency lag is the two-filter crossing time: 0.083 s for a 2.5 Hz
  step with the defaults.
- Equality is a knife edge: 5e-5 pu decides it, with no hysteresis.
- On a trip, FRACON (VAR L+3) steps to 1 − `FCEASE`.

**Reconnect.**
- After an undervoltage trip, `TDRA` times while `VRPA` < VFILT < `VRUPA`.
- After an overvoltage trip, `TRUPA` times in the same window.
- After a frequency trip, `TUFRN1`/`TOFRN1` times while
  `FUFRN1` < f < `FOFRN1`.
- Any exit from the window restarts the timer from zero. The ramp starts
  `CMTDELAYC` plus ~3 steps after the timer completes.
- `VRPA` is absolute, not relative to the initial voltage.
- **If `VRPA` is below a stage voltage, the block cycles:** it trips and
  reconnects every `TDRA` + `DMA` for as long as the voltage sits between
  them. No preset does this.

**Ramp.**
- FRACON rises linearly to 1 − `FCEASE` + `FCEASE`·`FRECON` over exactly
  `RAMPA`/`RAMPUA`/`RUFRN1`/`ROFRN1` seconds, whatever the span.
- Nothing pauses it, and the trip stage timers keep running during it.
- **Each `psspy.run` call advances the ramp one extra time step**, so a
  script that calls `run()` every step sees half-length ramps. A study that
  runs from event to event sees the CON exactly. The preset library's
  earlier "half-time ramps" finding was this rig effect.

**Power.**
- A current order Ip (STATE K+0) lags its target on `TRA`. The target is
  FRACON·Pref·VFILT^`NPA`·(1 + droop)·`LFM`/VFILT, clipped to
  [`IPMINA`, `IPMAXA`]. The block draws P = V·Ip/`LFM`.
- So in steady state P = min(Pref·V^`NPA`·(1 + droop), V·`IPMAXA`/`LFM`),
  floored at V·`IPMINA`/`LFM`. Q = min(Q0·V^`NQA`, V·`IQMAXA`/`LFM`), a
  separate limit.
- `LFM` is the block's power factor: the current base is MW/`LFM`.
- Pref = min(1, `IPMAXA`/`LFM`). With `IPMAXA` < `LFM`, the block cannot
  draw its power-flow load and drifts to `IPMAXA`/`LFM` at t = 0.
- Droop = `DROOPA`·db(f − 60, `DBA`)/60, where `DBA` is a non-step
  deadband **in Hz**. It is multiplicative with V^`NPA` and does not touch
  Q.
- These rules explain the sag-onset dip, the recovery overshoot to ~1/V_sag
  and the ~0.1 s post-trip decay. Rebuilt from traced inputs, the P loop
  matches PSS/E to ≤ 5 mpu RMS.

Every shipped preset has `VRPA` ≥ its highest undervoltage stage voltage and
`IPMAXA`/`LFM` ≥ 1.25, so none hits the cycling or initialisation cases.
**The app's simulator follows these rules**
(`src/load_models/perc1_dll/simulation.py`): the filtered trip and
reconnect logic with its window, cycling and communication delays, and the
current-order power loop with its limits and droop. Against the 458
single-event PSS/E traces that are not knife-edge equality tests, voltage
trips land within three PSS/E time steps (+2 to +11 ms). Trip and
reconnect-or-stay-tripped outcomes agree in every case but one, a hold 2 ms
past a stage's delay, which is inside PSS/E's step discretization. Frequency
trips land ~0.05 s early, because PSS/E's own bus-frequency filter (a study
setting) is not modelled. Steady power follows the same rule the probes
checked to 0.002 pu.

### DLL variant vs. the newer "Standard" PERC1 implementation

PERC1 has (at least) two distinct PSS/E implementations, and this app
supports both - the DLL variant described above as `perc1_dll`, the Standard
variant as `perc1_standard`:

| | DLL variant (`perc1_dll`) | "Standard" variant (`perc1_standard`) |
|---|---|---|
| PSS/E availability | v34, v35 | v36.5+ - PSS/E's own built-in standard model, not a separately-loaded DLL |
| Developed by | ISO New England (ISO/NE) | Cross-vendor PERC1 harmonization effort (PowerWorld/TSAT/PSLF/PSS/E) |
| Overvoltage cease/reconnect | Yes (`VDUA`/`TDUA` + `VRUPA`/`TRUPA`/`RAMPUA`) | **No** |
| Frequency cease/reconnect | Yes (one point per direction, Option 3) | **No** |
| Momentary cessation (Option 2) | Yes | **No** |
| Stepped multi-level trip (Option 3) | Yes (4-stage voltage; frequency has one stage) | **No** |
| Cross-vendor behavioral parity | Not claimed | Yes - built specifically to behave identically across PowerWorld/TSAT/PSLF/PSS/E |
| Parameters | 173 CONs - `load_models.perc1_dll.cons` | 30 CONs - `load_models.perc1_standard.cons`, limits and defaults measured in PSS/E 36.7.1 |
| `.dyr` record | `'USRLOD' ... 'PERCBL' 12 IT 2 173 33 250 0` | `'USRLODC' ... 'PERCBL1U' 230 IT 0 30 8 24 2 CompNum 'CompDesc'`, under a `MAINBL10` record |
| Needs a DLL | Yes (`PERC2_V35.dll`) | No |

The vendor's own DLL documentation states this directly: the DLL variant
(PSS/E v34/v35, ISO/NE) adds five features versus PSS/E's standard model -
(1) a high *and* low voltage ride-through no-trip zone, (2) high/low voltage
reconnection with a ramp rate, (3) a high *and* low frequency ride-through
no-trip zone, (4) high/low frequency reconnection with a ramp rate, and (5)
momentary cessation - which is exactly the DLL-vs-Standard row list above.
Separately, a Nov 2025 cross-vendor PERC1 harmonization presentation
(PowerWorld, to NERC's Load Modeling Task Force) independently described the
same gap from the other direction: the newer, standard model explicitly does
not yet include high-voltage or frequency-deviation cease/reconnect, calling
those candidate features for a possible future "PERC2." Both sources agree
on *what* is missing. The Standard variant's CONs, record format and limits
come from PSS/E 36.7.1's own `ModelLibrary.pdf` and were then checked against
the running program (435 tests, 262 automatic checks, in the PSS/E validation library, which is not published); the user page
[model_perc1_standard.md](../user/model_perc1_standard.md) lists every place the data sheet and PSS/E differ. It is a separate
registered load model, not a variant of this one.

### Key parameters

These are the parameters a preset sets per block, and the ones most often
edited by hand in the Screening and Post-Commissioning parameter rows. Every
field name below is the model's actual PSS/E CON mnemonic - not a simplified
alias - so a value shown in the app's parameter rows or HTML report maps
directly onto a specific position in the exported `.dyr` record.

| CON | Plain-English name | What it does | Default (`PERC1_DEFAULT_CONS`) |
|---|---|---|---|
| `VDPA` | Vcease | Trip voltage (pu) - block begins ceasing below this terminal voltage. | 0.70 |
| `DMA` | Tcease | Trip delay (s) - how long voltage must stay below `VDPA` before the block ceases. | 0.02 |
| `VRPA` | Vrecon | Reconnect voltage (pu) - voltage must recover above this before reconnection starts. | 0.90 |
| `TDRA` | Trecon | Reconnect delay (s) - time voltage must stay above `VRPA` before reconnection begins. | 60 |
| `RAMPA` | Tramp | Reconnect ramp rate (s) - how long the ramp back to full load takes once reconnection starts. | 30 |
| `FCEASE` | Fcease | Fraction of the block's load that ceases on trip. | 1.0 |
| `FRECON` | Frecon | Fraction of the ceased load that reconnects. | 1.0 |
| `NPA` | - | Active-power ZIP exponent: `0` = constant power, `1` = constant current, `2` = constant impedance. | 0 (set by the block's operating mode) |
| `NQA` | - | Reactive-power ZIP exponent, same 0/1/2 scale. | 0 (same as `NPA`) |
| `TRA` | Tt | Numerical filter time constant (s). | 0.02 |

The remaining ~20 "secondary" CONs (`VDUA`/`TDUA` high-voltage trip,
`DROOPA`, `IPMAXA`/`IPMINA`/`IQMAXA`/`IQMINA` current limits, and others) are
held at vendor-documented standard defaults but are still exposed for direct
editing in the parameter rows, since they are meaningful
engineering settings even though no preset changes them. `VDUA`/`TDUA` are channel A's real overvoltage cease threshold/delay
- the DLL variant's own counterpart to `VDPA`/`DMA` on the high side, paired
with a `VRUPA`/`TRUPA`/`RAMPUA` reconnect block (the Voltage ride-through
row's "Overvoltage reconnect" section) the same way `VRPA`/`TDRA`/`RAMPA` pairs with
`VDPA`/`DMA`. The live-preview simulation reconnects an overvoltage trip on
`TRUPA`/`RAMPUA`, inside the `VRPA` < V < `VRUPA` window, as PSS/E does. The
full set of CONs this app is aware of for the DLL variant - all 173, in exact
model order - lives in `src/load_models/perc1_dll/cons.py` as `PERC1_CON_ORDER`.

### Defaults, operating mode and presets

- **Defaults.** A new block starts from `PERC1_DEFAULT_CONS`
  (`src/load_models/perc1_dll/cons.py`): `PERC1_FIXED_DEFAULTS` plus the
  table above, which is the generic Standard (ITIC/CBEMA) tier for a
  double-conversion UPS that trips fully and reconnects in stages.
- **UPS operating mode / VFD front-end type** sets the ZIP exponent
  `NPA`/`NQA` (`ZIP_EXPONENT_MAP`): a tightly-regulated front end
  (double-conversion UPS, active-front-end VFD) is modeled as constant power
  (`0`) since it holds its power draw roughly constant through a sag until it
  trips; an unregulated/direct-online load is modeled closer to constant
  impedance (`2`), since its current draw - and hence power - falls off with
  voltage.
- **Presets.** The three generic tiers (Extended / Standard / Minimal,
  walked through in [`docs/user/parameter_tiers.md`](../user/parameter_tiers.md))
  and the utility ride-through presets (ERCOT, SPP, PJM, MISO, either NERC
  entry) each drive every one of these CONs from their own numbers - see
  [`docs/user/presets/`](../user/presets/README.md).

### The exported `.dyr` record

Both the IT/UPS and Cooling VFD blocks are written as PSS/E `USRLOD` records
matching the vendor's exact PERC1 data sheet:

```
IBUS 'USRLOD' 'ID' 'PERC**' 12 IT 2 173 33 250 0
ICON(M) ICON(M+1)
CON(J) ... CON(J+172)   / 173 values, in exact model order
```

A few things worth knowing when reading the output:

- **Record format.** The vendor's "DYRE FORMAT" section sets the model name
  suffix and the `IT` code together. The app's **Record format** selector
  (PSS/E records panel; `perc-studio export dyr --scope`) writes:

  | Record format | Model name | `IT` | First field |
  |---|---|---|---|
  | Bus | `PERCBL` | 1 | Bus number |
  | Owner | `PERCOW` | 2 | Owner number |
  | Zone | `PERCZN` | 3 | Zone number |
  | Area | `PERCAR` | 4 | Area number |
  | All | `PERCAL` | 5 | 0 |

  CLOD records follow the same scope (`CLODBL`, `CLODOW`, `CLODZN`,
  `CLODAR`, `CLODAL`). The model-name and `IT` columns are the vendor's; the
  first-field column is the standard PSS/E convention for subsystem load
  models, which the vendor text does not spell out (it only shows the bus
  form).
- Like CLOD, **PERC1 carries no MW/Mvar of its own** - it is a `USRLOD` model
  that attaches to an existing static Load record in the power flow (`.raw`
  case), matched by bus number and load ID. The `.dyr` file's comments call
  out each block's approximate MW so you can cross-check against the
  corresponding static Load record.
- The file is written with the same `@!`-commented, grouped-row layout as the
  vendor's own example `.dyr` file, so each row of numbers is self-labeled
  with its CON names directly above it.

## The CLOD load model (cooling motor block)

The optional Cooling Motor block uses PSS/E's `CLODBL` (baseline generic
composite load) model to represent conventional (non-VFD) motor-driven
cooling equipment - CRAC units, fixed-speed fans and pumps, chillers, etc.
Unlike PERC1, CLOD's trip/stall behavior is governed by fixed internal
electromechanical parameters (inertia, stall voltage/time), not by
user-configurable CONs, so there is no equivalent trip-threshold value to
set. What the app *does* derive is the load's
composition - the percentage split across:

| Parameter | Meaning |
|---|---|
| `PC_LM` | Large motor share |
| `PC_SM` | Small motor share |
| `PC_TX` | Transformer exciting current share |
| `PC_DL` | Discharge lighting share |
| `PC_CP` | Constant power share |

based on a facility archetype (Modern / Mixed / Legacy) and whether the block
includes significant lighting/office load. See `derive_clod_params` in
`src/load_models/clod/cons.py`.

## HTML report and live response plots

Both the Screening and Post-Commissioning tabs show, per PERC1 block, a live
three-panel Plotly chart (`build_perc1_response_figure` in
`src/preview/perc1_dll.py`) simulating the block's response to a normally-cleared
fault. The fault's duration (in cycles) and depth (a signed pu deviation from
nominal - positive is a sag, negative is a swell) are both adjustable via
sliders, and the chart re-renders live (`Plotly.react()`, no page reload) on
every slider or advanced-CON-field change:

1. **Voltage vs. time** - the simulated voltage trace, with three
   reference zones (undervoltage-trip-permitted, normal, overvoltage-trip-
   permitted) drawn from stage 1's own `VDPA`/`VDUA` and the ride-through/
   reconnect boundary (`VRPA`), so both trip directions are visible at once.
2. **Power output vs. time** - the resulting fraction of block MW online,
   showing the trip (if any, and which direction and which of the 4 stages
   caused it) and the reconnect ramp. `load_models.perc1_dll.simulation.simulate_perc1_response`
   evaluates all 4 undervoltage and all 4 overvoltage stages, exactly the
   way the compiled DLL does (see [Option 3 is always live](#option-3-is-always-live)): for this
   app's single constant-depth fault shape, every stage the fault's depth
   crosses starts counting down from the same fault onset, and whichever
   armed stage's own dwell time elapses first is the one that actually
   trips - not necessarily stage 1's `VDPA`/`DMA` or `VDUA`/`TDUA`. A preset
   whose stage 2 has a shorter dwell than stage 1 (e.g. ERCOT NOGRR282's
   `DMA1=0.50s` vs. `DMA=2.00s`) can visibly trip well before stage 1's own
   point would ever predict.

   **A "rides through" result that's actually just one slider-drag away from
   tripping says so.** A real, reported point of confusion: ERCOT NOGRR282's
   *only* overvoltage tier requires a full 2.00s hold above 1.20pu - much
   longer than any of its undervoltage tiers (as short as 0.15s) - so a
   0.6s swell to 1.25pu correctly rides through, exactly like the 0.1s swell
   in the overvoltage probe above did against the real DLL. Without more context this looks identical to a depth that never
   reaches any threshold at all - it isn't a bug in either case, but the two
   are very different findings. Whenever the current depth arms a stage that
   simply hasn't been held long enough, the caption states the exact
   requirement (`"rides through (would trip after 2.00s held)"`) and a
   dashed amber reference line marks where the trip would occur if the fault
   were held that long (`load_models.perc1_dll.simulation.simulate_perc1_response`'s
   `armed_required_delay_s`).
3. **Trip threshold vs. ride-through envelope** - compares all 4 of this
   block's undervoltage stage points and all 4 overvoltage stage points
   (`VDPA`/`DMA` + `VDPA1-3`/`DMA1-3`, `VDUA`/`TDUA` + `VDUA1-3`/`TDUA1-3`)
   against the *selected ride-through preset's own* two-sided tolerance
   envelope (see `src/presets/ridethrough.py`), each with its own
   independent pass/fail verdict. This panel does **not** compare against the ITIC/CBEMA curve -
   ITIC is a 1970s equipment power-quality tolerance curve, not a
   bulk-power-system reliability standard, and isn't what any grid operator
   or NERC standard actually benchmarks against (see
   [`docs/user/presets/README.md`](../user/presets/README.md#why-these-numbers-and-not-iticcbema)
   and the preset library's own citations for the primary sources behind
   each standard's numbers).

Every dynamic label is either placed in a fixed non-overlapping legend
position or backed by an opaque chip, so labels stay legible regardless of
the specific parameter values being plotted. The saved HTML report embeds a
static snapshot of the same chart for a fixed illustrative scenario - useful
for engineering review, not a substitute for an EMT/stability simulation.

## Related documentation

- [README.md](../../README.md) - orientation, getting started, how to run the app.
- [docs/user/parameter_tiers.md](../user/parameter_tiers.md) - the generic
  ride-through tiers, the CON values each produces, and the justification
  for each.
- [docs/user/presets/](../user/presets/README.md) - the
  utility/RTO/ISO ride-through preset library, one page per standard with
  its own primary-source citation.
- [docs/developer/ARCHITECTURE.md](ARCHITECTURE.md) - project layout and what each
  source module is responsible for.
