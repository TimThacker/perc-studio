# The PERC2 DLL v2.3 model (`PERC2_v3x_v2p3.dll`, `PERCBL` with 179 CONs)

The developer reference for `src/load_models/perc2_dll/` (model id `perc2_dll`): what the model is, its record, the
values it adds to the PERC1 DLL, how the app fills them from a preset, and what the DLL does that its document does not
say. Derived from the PSS/E validation library (not published); results are summarized here and in the user model pages.

## What it is

ISO-NE's PERC2 v2.3 is **the PERC1 DLL (`perc1_dll`, [PERC1_MODEL.md](PERC1_MODEL.md)) with six CONs appended**, built
for PSS/E 34, 35 and 36 (`PERC2_v34_v2p3.dll`, `PERC2_v35_v2p3.dll`, `PERC2_v36_v2p3.dll`; the app validated the v35 and
v36 builds). It is a user load model (`USRLOD`), not a composite-load component, and it registers the same model name as
the PERC1 DLL, `PERCBL`. Everything the two share behaves identically (79 cases, identical traces outside the voltage
reconnect ramps). It is unrelated to PSS/E's built-in PERC2 *standard* model ([PERC2_MODEL.md](PERC2_MODEL.md)).

| | PERC1 DLL (`perc1_dll`) | **PERC2 DLL v2.3 (`perc2_dll`)** | PERC2 standard (`perc2_standard`) |
|---|---|---|---|
| PSS/E | 34, 35 (DLL) | 34, 35, 36 (one DLL per version) | 36.7 built in |
| Record | `USRLOD 'PERCBL' 12 IT 2 173 33 250 0` | `USRLOD 'PERCBL' 12 IT 2 179 33 250 0` | `USRLODC 'PERCBL2U'` under `MAINxx10` |
| Values | 2 ICONs + 173 CONs | 2 ICONs + **179** CONs | 6 flags + 57 CONs |
| Stages | 4 under, 4 over, 1 frequency each way | same | momentary + 4-point long tables |
| Momentary cessation return | `VLBLK < V < VUBLK`, ramp `RAMPA` | **`VLRCMC < V < VURCMC`, ramp `RAMPAMC`/`RAMPUAMC`** | `VLrecon < V < VHrecon` |
| Ramp in seconds | every ramp CON as given | **`RAMPA`, `RAMPUA` x LFM**; the rest as given | `Tramp x Ldfact` |
| Reactive lead-lag | none | `TAQ`/`TBQ` | `Taq`/`Tbq` |

## The record

```
IBUS 'USRLOD' 'ID' 'PERC**' 12 IT 2 179 33 250 0
 ICON(M) ICON(M+1)
 CON(J) .. CON(J+172)        (the PERC1 DLL's 173, in its row groups)
 TAQ TBQ
 RAMPAMC RAMPUAMC
 VLRCMC VURCMC /
```

`dyr.py` writes it with the PERC1 DLL's `@!` comment rows plus three, the two ICONs on their own line. The document's
own `DYRE FORMAT` says 173 CONs; that record loads silently and breaks momentary cessation, so the app never writes it
(validation finding 1.2). The app keeps the two ICONs in the CON dict as integers, `FREQ50` (ICON(M)) and `MCFLAG` (ICON(M+1)),
like the PERC2 standard model's flags.

**Telling it from a PERC1 DLL record.** Both say `PERCBL`. `perc1_dll/dyr.py`'s `parse_perc1_records` reads either
layout and sets `n_con` from the header; `is_perc1_dll_record` / `is_perc2_dll_record` test it, and both models set the
new `LoadModel.matches_dyr` hook, which `find_model_for_dyr` checks after the name. A header too broken to read counts as
PERC1's, so the error is reported against the older model. `.dyr` import routes the same way.

## The new values

| Value | Meaning (measured) |
|---|---|
| `FREQ50` (ICON(M)) | The document's 50 Hz flag. **Ignored**: the DLL always measures 60 Hz x (1 + deviation). The app writes 0 and warns on anything else |
| `MCFLAG` (ICON(M+1)) | 1 = momentary cessation on; any other value is off |
| `TAQ`, `TBQ` | Q lead-lag (1 + sTAQ)/(1 + sTBQ). Both 0 bypasses it; TAQ with TBQ = 0 returns NaN |
| `RAMPAMC`, `RAMPUAMC` | ramp after a low / high cessation, in seconds (not x LFM) |
| `VLRCMC`, `VURCMC` | a ceased load comes back after the filtered voltage has been strictly inside this band for `TBLK + TDELY` |

The defaults are the PERC1 DLL's (`perc1_dll`'s `PERC1_DEFAULT_CONS`), the four cessation CONs from the vendor sample
(1.0, 1.0, 0.9, 1.09), TAQ = TBQ = 0, MCFLAG = FREQ50 = 0, and RAMPA/RAMPUA divided by LFM so a new block ramps over the
same seconds as a new PERC1 DLL block.

## The cease / reconnect machine

The PERC1 DLL's, as PERC1_MODEL.md "Measured runtime behavior" describes it, with:

- **Ramps.** RAMPA and RAMPUA last their CON x LFM (LFM < 0.001 counts as 0.8). RUFRN1, ROFRN1, RAMPAMC and RAMPUAMC
  last their CON. `cons.ramp_seconds()` is the one place this rule lives.
- **Momentary cessation** (MCFLAG = 1 and FCEASE > 0). The filtered voltage strictly below `VLBLK` or above `VUBLK`
  ceases the load at once (no CMTDELAY): FracOn = 1 - FCEASE. It returns after `TBLK + TDELY` strictly inside
  `VLRCMC < V < VURCMC` (the timer restarts if V leaves), ramping over `RAMPAMC`/`RAMPUAMC` to 1 - FCEASE + FRECON x
  FCEASE - the same partial return as a trip. CMTDELAYC and RAMPA play no part.
- **Stage takeover.** The stage timers keep running during a cessation. A stage that trips turns it into an ordinary
  trip: the load then needs `VRPA < V < VRUPA` for TDRA (+ CMTDELAYC) and ramps over RAMPA x LFM. With stages at or
  below VLBLK, a sag longer than the stage delay always ends on the slow path.
- A new cessation (or trip) during any ramp ceases again from where the ramp had got to.

## Ride-through presets (`presets.py`)

A preset's PERC1 DLL bundle carries over CON for CON (`it_bundle` / `vfd_bundle`), with three changes:

- RAMPA and RAMPUA are divided by LFM, so the preset reconnects over the same seconds as on the PERC1 DLL.
- **VRPA is capped at 0.95 pu** (`RECONNECT_VOLTAGE_CEILING`, the PERC2 standard presets' ceiling). Five presets (ERCOT
  NOGRR282, PJM, MISO, NERC LLWG, PRC-029) set VRPA = 1.0, which never reconnects after a recovery to 1.0 pu because the
  window is strict on a voltage that approaches 1.0 from below (the PERC1 DLL preset library's finding 1, and validation finding
  section 3 on v2.3). `preset_gaps(preset)` says so for the presets it changes.
- Momentary cessation stays off; the four new cessation CONs take the vendor sample's values and TAQ = TBQ = 0.

## `validate_cons`

`validate_cons(cons, time_step_s, initial_voltage_pu, psse_version=None)` returns `ConIssue(level, con, message)`; an
empty list means the values mean in PSS/E what they say. Errors are values the DLL turns into nonsense: FCEASE outside
[0, 1] and negative FRECON (not clamped: the load exports power or ramps down), negative ramps (FracOn runs below zero),
TA or TAQ without TB/TBQ (NaN), IPMAXA <= 0, a stage threshold on the wrong side of the initial voltage, a reconnect
window or cessation band that excludes it; with `psse_version="36.7"`, any TA/TB (NaN) and momentary cessation with a
reachable VUBLK (the v36 build exits at the end of a high-side cessation ramp). Warnings: ICON(M) set, LFM replaced,
cycling (VRPA below a stage, VRUPA above one), IPMAXA < LFM, FRECON < 1 with cessation on (permanent loss per
cessation), a stage at or below VLBLK with cessation on (the takeover), FRA/VNOMA not 1, TRA below 2 time steps.

## The simulator

`simulation.py`: with momentary cessation off, the PERC1 DLL simulator on `perc1_equivalent(cons)` (RAMPA/RAMPUA in
seconds, LFM as the DLL uses it, negative delays as 0). With it on, a v2.3 state machine (`_run_logic`) that adds the two
cessation "stages" (zero delay, their own band and ramps), keeps the stage timers running during a cessation, and
marks a takeover (`escalated` in the response); the filters, the power loop and the response shape are the PERC1 DLL
simulator's. Checked against PSS/E on every single-dip case of the library (79, 31 with cessation): first cease, first
ramp start and ramp length agree within one sample (validation finding 10). Not modelled: the lead-lags and washouts (the
app exports them bypassed), the per-`run()`-call ramp speed-up (a rig effect), Q.

## DLL issues the app works around

| Issue | What the app does |
|---|---|
| The document's 173-CON format breaks momentary cessation | always writes 179 |
| Same model name as the PERC1 DLL | routes records by CON count; the report and import label which DLL a record needs |
| ICON(M) ignored | writes 0; warns otherwise |
| RAMPA/RAMPUA x LFM (the PERC1 DLL does not scale) | divides them by LFM in defaults and presets |
| VRPA 1.0 never reconnects | caps preset VRPA at 0.95, reports it in `preset_gaps` |
| v36 build: high-side cessation crashes PSS/E 36.7; any TA/TB is NaN | `validate_cons(..., psse_version="36.7")` errors; the app exports TA = TB = 0 and cessation off by default |
| No range checks in the DLL | `validate_cons` errors before export (`build_perc2_dll_dyr_block` refuses errors) |
