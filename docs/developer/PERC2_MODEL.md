# The PERC2 standard model (PSS/E 36.7 `PERCxx2U`)

The developer reference for `src/load_models/perc2_standard/` (model id `perc2_standard`): what the model is, its
record, every flag and CON, how the app fills them from a preset, and what PSS/E 36.7.1 does that its data sheet does
not say. Derived from the PSS/E validation library (not published); results are summarized here and in the user model pages.

## What it is

PERC2 is PSS/E's built-in power-electronic load component (Fortran source `percbl2.for`, compiled into PSS/E 36.7; no
DLL). Like PERC1 standard (`PERCxx1U`, [PERC1_MODEL.md](PERC1_MODEL.md)) it is a component of PSS/E's composite load, so
it sits under a `MAINxx10` record and the composite-load thresholds switch it off (load below 5 MW, |P/Q| below 1.61,
load-bus voltage at or below 0.97 pu). Compared with the two PERC1 models:

| | PERC1 DLL (`perc1_dll`) | PERC1 standard (`perc1_standard`) | PERC2 standard (`perc2_standard`) |
|---|---|---|---|
| PSS/E | 34, 35 (DLL) | 36.5+ built in | 36.7 built in |
| Values | 173 CONs | 30 CONs | 6 flags (ICONs) + 57 CONs |
| Undervoltage cease | 4 stages + Option 1 point | one point | a momentary point + a 4-point long table (3 usable in 36.7.1) |
| Overvoltage cease | 4 stages | none | a momentary point + a 4-point long table (3 usable) |
| Frequency cease | one point each way, reconnects | none | one point each way, **never reconnects** |
| Reconnect settings | per direction | one set | per cease level: momentary, long low, long high |
| Reconnect window | `VRPA < V < VRUPA` | `V > Vrecon` | `VLrecon < V < VHrecon` |
| Ramp CON | seconds | seconds | `Tramp x Ldfact` seconds |
| Current limits | per axis | per axis | per axis plus `Imax`, active current first |

The full behavioral comparison is in the PSS/E validation library (not published).

## The record

```
IBUS 'MAINxx10' ID 1 0 0 0 0 0 0 0 0 0  1 0 0 0 0 0 0 0 0 0 /
IBUS 'USRLODC' ID 'PERCxx2U' 230 IT 6 57 8 44 16 CompNum 'CompDesc' <6 flags> <57 CONs> /
```

`xx`/`IT` are the record scope (BL 1, OW 2, ZN 3, AR 4, AL 5 with first field 0). The numbers after `IT` are NICON (6
flags), NCON (57), NSTATE (8), NVAR (44) and the reserved-ICON count (16). **Write them exactly**: PSS/E does not check
them against the model, a short count makes PERC2 overwrite the next component's memory (a neighbouring PERC1U lost its
whole 50 MW at NVAR 40), and a later record with different counts is dropped as "Inconsistent model definitions"
(validation finding 2.2). The flags must be integers (`1.0` is rejected). `dyr.build_perc2_standard_dyr_block` writes the flags on
the header line and the CONs ten per continuation line, adds an `LSTCxx` static remainder (fraction -1) for a partial
load, and refuses values `validate_cons` marks as errors.

## Flags and CONs

Generated from `cons.CON_SPECS` (labels, units and notes are the code's own); the default is `cons.DEFAULT_CONS`.

| Slot | Name | Meaning | Unit | Default | Measured in PSS/E 36.7.1 |
|---|---|---|---|---|---|
| M+0 | `VLMflag` | Momentary low-voltage cease | flag | 1 | 1 checks Vtf < VLcease for Tcease; any other value (0, 2, -1) is off. |
| M+1 | `VHMflag` | Momentary high-voltage cease | flag | 0 | 1 checks Vtf > VHcease for Tcease. Off still leaves VHcease capping VHrecon. |
| M+2 | `VLLflag` | Long low-voltage cease (4-point table) | flag | 0 | 1 checks Vtf < VLCx for TVLCx. PSS/E 36.7.1 times point 3 with TVLC1, not TVLC3. |
| M+3 | `VLHflag` | Long high-voltage cease (4-point table) | flag | 0 | 1 checks Vtf > VHCx for TVHCx. PSS/E 36.7.1 times point 3 with TVHC1, not TVHC3. |
| M+4 | `FLflag` | Low-frequency cease (no reconnect) | flag | 0 | 1 checks f < FLC1 for TFLC1. The load then does not come back. |
| M+5 | `FHflag` | High-frequency cease (no reconnect) | flag | 0 | 1 checks f > FHC1 for TFHC1. The load then does not come back. |
| J | `Ldfact` | Load factor (sets the MVA base) | pu | 0.8 | MVA base = initial P / Ldfact; every pu CON is on that base. <= 0 -> PSS/E uses 0.8 (with a message). The data sheet says > 1 also falls back to 0.8; PSS/E 36.7.1 uses it as given, and the block then cannot draw its own power-flow load if Ldfact > Ipmax. |
| J+1 | `QPratio` | Q/P ratio (initial reactive power) | pu | 0 | Qinit = QPratio x Pinit. The difference to the load's power-flow Q is absorbed as ExtraVars. |
| J+2 | `Tt` | Converter delay | s | 0.02 | PSS/E raises anything below 2 x time step to 2 x time step. The data sheet says it writes a message; 36.7.1 does not. |
| J+3 | `Tv` | Voltage measurement time constant | s | 0.05 | Filters the voltage every voltage check sees. 0 or negative = no filter. |
| J+4 | `Tf` | Frequency measurement time constant | s | 0.02 | Filters the frequency for droop and the frequency cease. Its input is held at 0 deviation while the bus voltage is below 0.7 pu. |
| J+5 | `dbfl` | Droop deadband, lower edge | pu freq | 0 | A frequency deviation (0.005 pu = 0.3 Hz), <= 0. |
| J+6 | `dbfh` | Droop deadband, upper edge | pu freq | 0 | >= 0. |
| J+7 | `Kdroop` | Droop gain | pu P / pu f | 8 | dP = Kdroop x (df - deadband) in pu of the MVA base; P falls when f falls. 0 disables. |
| J+8 | `Kvp` | P-path washout gain | pu*s | 0 | Washout sK/(1+sT) on the bus voltage, added to Pinit. 0 disables. |
| J+9 | `Tvp` | P-path washout time constant | s | 0.05 | Keep > 0 when Kvp != 0. |
| J+10 | `Kvq` | Q-path washout gain | pu*s | 0 | 0 disables. |
| J+11 | `Tvq` | Q-path washout time constant | s | 0.1 | Keep > 0 when Kvq != 0. |
| J+12 | `Tap` | P-path lead time constant | s | 1 | Lead-lag (1+sTap)/(1+sTbp) on Pinit + droop + washout. |
| J+13 | `Tbp` | P-path lag time constant | s | 1 | 0 bypasses the whole P lead-lag (Tap is then ignored), as in PERC1 standard. |
| J+14 | `Taq` | Q-path lead time constant | s | 1 | Lead-lag (1+sTaq)/(1+sTbq) on Qinit + washout. |
| J+15 | `Tbq` | Q-path lag time constant | s | 1 | 0 bypasses the whole Q lead-lag. |
| J+16 | `nP` | P voltage exponent | - | 0 | P = P0 (Vtf/Vinit)^nP in steady state: 0 constant power, 1 current, 2 impedance. |
| J+17 | `nQ` | Q voltage exponent | - | 0 | Same for Q. |
| J+18 | `Ipmax` | Maximum active current | pu | 1 | IpmaxUsed = min(Ipmax, Imax) (the block diagram; the sheet's note 16 says max, PSS/E uses min). Below Ldfact the block cannot draw its power-flow load at 1.0 pu. |
| J+19 | `Ipmin` | Minimum active current | pu | 0 | IpminUsed = max(Ipmin, -Imax). Keep >= 0 or the load backfeeds. |
| J+20 | `Iqmax` | Maximum reactive current | pu | 0.7 | IqmaxUsed = min(Iqmax, sqrt(Imax^2 - Ip^2)): active current has priority. |
| J+21 | `Iqmin` | Minimum reactive current | pu | -0.7 | IqminUsed = max(Iqmin, -sqrt(Imax^2 - Ip^2)). |
| J+22 | `Imax` | Maximum total current | pu | 1.5 | Must be > 0: 0 zeroes the load; a negative value is used as its magnitude. |
| J+23 | `fcease` | Fraction that ceases | - | 0.9 | Outside [0,1] PSS/E clamps it (with a message). 0 turns every cease off. |
| J+24 | `VLcease` | Momentary cease, low voltage | pu | 0.5 | Strictly Vtf < VLcease for Tcease ceases (VLMflag). Above the initial voltage the load ceases at t = 0. |
| J+25 | `VHcease` | Momentary cease, high voltage | pu | 1.2 | Strictly Vtf > VHcease for Tcease ceases (VHMflag). Even with VHMflag off, VHrecon is capped at it: a VHcease below the post-event voltage means the load never reconnects. |
| J+26 | `Tcease` | Momentary cease delay | s | 0.05 | Recovering earlier cancels it; two short dips do not accumulate. Negative acts as 0. |
| J+27 | `Tdelay` | Extra delay before the load is reduced | s | 0 | Tdelay adds to every cease path (momentary, long and frequency) in PSS/E 36.7.1; unlike PERC1 standard, a dip that ends while it runs does not collapse FracOn (PERC1 standard's collapse is followed by NaN, a wrong load or a normal result, intermittently; validation finding 8). |
| J+28 | `frecon` | Fraction of fcease that reconnects | - | 0.5 | Final FracOn = (1 - fcease) + frecon x fcease; > 1 returns above the initial load; negative acts as 0. |
| J+29 | `VLrecon` | Reconnect window, low edge | pu | 0.6 | Reconnection needs VLrecon < Vtf < VHrecon. Raised to VLcease if lower. A long-cease threshold above it lets the load reconnect while still in the sag and cease again (cycling). |
| J+30 | `VHrecon` | Reconnect window, high edge | pu | 1.1 | Lowered to VHcease if higher (whatever VHMflag is). |
| J+31 | `Tramp` | Reconnect ramp (momentary cease) | s | 1.25 | The ramp lasts Tramp x Ldfact seconds (TrampUsed). 0 or negative = instant. |
| J+32 | `Trecon` | Reconnect delay (momentary cease) | s | 0.05 | Time inside the reconnect window before the ramp starts. Negative acts as 0. |
| J+33 | `TLrampL` | Reconnect ramp after a long low-voltage cease | s | 1.25 | Used as TLrampL x Ldfact. |
| J+34 | `TLreconL` | Reconnect delay after a long low-voltage cease | s | 0.05 | 0 or negative: the ramp starts the moment the load ceases if Vtf is inside the reconnect window. |
| J+35 | `VLC1` | Long low-voltage point 1, voltage | pu | 0.9 | Vtf < VLC for TVLC ceases (VLLflag). |
| J+36 | `TVLC1` | Long low-voltage point 1, time | s | 2 | 0 or negative = as soon as Vtf is below the point. Also times point 3. |
| J+37 | `VLC2` | Long low-voltage point 2, voltage | pu | 0.8 | Vtf < VLC for TVLC ceases (VLLflag). |
| J+38 | `TVLC2` | Long low-voltage point 2, time | s | 0.5 | 0 or negative = as soon as Vtf is below the point. |
| J+39 | `VLC3` | Long low-voltage point 3, voltage | pu | 0 | PSS/E 36.7.1 ceases after TVLC1 (point 1's time) below this, not after TVLC3. |
| J+40 | `TVLC3` | Long low-voltage point 3, time | s | 0 | Not used by PSS/E 36.7.1 (point 3 waits TVLC1). |
| J+41 | `VLC4` | Long low-voltage point 4, voltage | pu | 0.5 | Vtf < VLC for TVLC ceases (VLLflag). |
| J+42 | `TVLC4` | Long low-voltage point 4, time | s | 0.15 | 0 or negative = as soon as Vtf is below the point. |
| J+43 | `TLrampH` | Reconnect ramp after a long high-voltage cease | s | 1.25 | Used as TLrampH x Ldfact. |
| J+44 | `TLreconH` | Reconnect delay after a long high-voltage cease | s | 0.05 | - |
| J+45 | `VHC1` | Long high-voltage point 1, voltage | pu | 1.1 | Vtf > VHC for TVHC ceases (VLHflag). |
| J+46 | `TVHC1` | Long high-voltage point 1, time | s | 1 | Also times point 3. |
| J+47 | `VHC2` | Long high-voltage point 2, voltage | pu | 1.15 | Vtf > VHC for TVHC ceases (VLHflag). |
| J+48 | `TVHC2` | Long high-voltage point 2, time | s | 0.5 | - |
| J+49 | `VHC3` | Long high-voltage point 3, voltage | pu | 99 | PSS/E 36.7.1 ceases after TVHC1 (point 1's time) above this, not after TVHC3. |
| J+50 | `TVHC3` | Long high-voltage point 3, time | s | 0 | Not used by PSS/E 36.7.1 (point 3 waits TVHC1). |
| J+51 | `VHC4` | Long high-voltage point 4, voltage | pu | 1.2 | Vtf > VHC for TVHC ceases (VLHflag). |
| J+52 | `TVHC4` | Long high-voltage point 4, time | s | 0.16 | - |
| J+53 | `FLC1` | Low-frequency cease threshold | Hz | 58 | f < FLC1 for TFLC1 ceases for good (FLflag). At or above the initial frequency the load ceases at t = TFLC1 with no disturbance. |
| J+54 | `TFLC1` | Low-frequency cease time | s | 100 | - |
| J+55 | `FHC1` | High-frequency cease threshold | Hz | 62 | f > FHC1 for TFHC1 ceases for good (FHflag). |
| J+56 | `TFHC1` | High-frequency cease time | s | 100 | - |

### The defaults

The sheet has no example values. `DEFAULT_CONS` reproduces PERC1 standard's defaults through the sheet's note-7 recipe
(`VLMflag` only, `VLcease = Vcease`, `Tramp = PERC1 Tramp / Ldfact`), so a new PERC2 block behaves like a new PERC1
standard block. `VHcease` 1.2 / `VHrecon` 1.1 keep the reconnect window above 1.0 pu, and the long and frequency tables
hold a generic table but are switched off. `validate_cons(DEFAULT_CONS)` is empty; switching `VLLflag` on with the
default `VLrecon` 0.6 gives the cycling warning, on purpose.

## The cease / reconnect machine

`simulation.CeaseLogic` is this state machine; validation finding 5 has the evidence.

1. **Checks.** VLM (`Vtf < VLcease` for `Tcease`), VHM (`Vtf > VHcease`, `Tcease`), VLL points 1-4 (`Vtf < VLCx`,
   `TVLCx`; point 3 waits `TVLC1`), VLH points 1-4 (`Vtf > VHCx`, `TVHCx`; point 3 waits `TVHC1`), FL (`f < FLC1`, `TFLC1`),
   FH (`f > FHC1`, `TFHC1`). Each has its own timer, started when its condition becomes true and reset when it is not;
   all comparisons are strict. `Vtf` is the voltage through `Tv`; `f` is PSS/E's bus frequency through `Tf`, with the input
   held at nominal while the bus voltage is below 0.7 pu.
2. **Cease.** A completed check starts `Tdelay`; then FracOn = `1 - fcease`, and the **cease level** is the check's: 0
   (momentary), 1 (long) or 2 (frequency). The level picks the reconnect delay and ramp: `Trecon`/`Tramp`,
   `TLreconL`/`TLrampL`, `TLreconH`/`TLrampH` (ramps x `Ldfact`), or never.
3. **While ceased** only checks of a higher level keep timing (escalation: momentary -> long -> frequency).
4. **Reconnect** at levels 0 and 1: the timer runs while `max(VLrecon, VLcease) < Vtf < min(VHrecon, VHcease)` and
   restarts when Vtf leaves; then FracOn ramps linearly to `(1 - fcease) + frecon x fcease`. Every check timer restarts at
   the ramp start, and any check can cease the load again during the ramp.

## Ride-through presets (`presets.py`)

A preset's CONs come from its PERC1 DLL bundle (`it_bundle` / `vfd_bundle`), so the three PERC models assume the same
facility physics:

| PERC2 | From the bundle |
|---|---|
| long low points 1, 2, 4 | the distinct undervoltage stages (`VDPA/DMA`, `VDPA1-3/DMA1-3`), shallowest first, padded by repeating the last |
| momentary low (`VLMflag`, `VLcease`, `Tcease`) | only for a fourth distinct stage (ERCOT, PRC-029); its reconnect settings equal the long ones |
| point 3 | off: `VLC3 = 0`, `VHC3 = 99` (the PSS/E defect) |
| long high points 1, 2, 4 | the distinct overvoltage stages, reconnecting with `TRUPA` / `RAMPUA` |
| `VLrecon` | max(min(`VRPA`, 0.95), the highest long-low threshold): above the long points so it cannot cycle, at most 0.95 so a 1.0 pu recovery reconnects |
| `VHrecon`, `VHcease` | min(`VRUPA`, the lowest long-high threshold); `VHcease` never below it |
| frequency | `FUFTP1/TUFTP1`, `FOFTP1/TOFTP1`, flags on; the cease is permanent in PERC2 |
| `Trecon`, `Tramp` | `TDRA`, `RAMPA / Ldfact` (also the long-low pair) |
| droop, limits, exponents, filters | `DROOPA x LFM`, `+-DBA/60`, `IPMAXA`..`IQMINA`, `NPA`/`NQA`, `TRA`/`TVM`/`TFRQ`; `Imax = sqrt(Ipmax^2 + Iqmax^2)` so it never binds by itself |

Every preset passes `validate_cons` with no issue, and every one (IT and VFD, under- and overvoltage) was exported and run
in PSS/E 36.7.1 (`app_preset_*`). `preset_gaps` lists the permanent frequency cease and the `VRPA` ceiling.

## `validate_cons`

Returns `error` for values that make the record meaningless in PSS/E (Imax 0; Ipmax < Ipmin; a reconnect window that
excludes the initial voltage, including `VHcease` below it with `VHMflag` off; an active threshold on the wrong side of
nominal; `FLC1`/`FHC1` on the wrong side of 60 Hz) and `warning` for what PSS/E changes silently or what is a hazard
(`Ldfact` outside (0, 1]; `min(Ipmax, Imax) < Ldfact`; flags other than 0/1; negative timers; `Tt < 2 x delt`; the
`VLrecon`/`VHrecon` clamps; an active point 3; a long point above the reconnect window). `post_fault_peak_warning` is
PERC1 standard's, with `Imax` as a cap.

## The simulator

`simulation.run_profile(cons, v_of_t, f_of_t, t_end)` steps the quarter-cycle grid; `simulate_perc2_standard_response` and
`simulate_perc2_standard_frequency_response` wrap it for the `LoadModel` hooks and add `trip_events`, `reconnect_events`,
`cycles`, `cease_check`, `cease_level`, `never_reconnects` and `stays_tripped_reason`. It models the state machine above,
the filters and the 0.7 pu gate, the steady-state exponents, the P-priority limits, the `Tt` lag and droop; not the
washout and lead-lag dynamics. Driven by PSS/E's own bus voltage and frequency, it gives PSS/E's cease/reconnect sequence
in every comparable library case (`tests/test_perc2_standard_simulation.py`; the `sim` section of the library's
`summary.md`). Known difference: in a cycling sag PSS/E re-ceases 4 time steps later per cycle.

## PSS/E 36.7.1 issues the app works around

| Issue | Workaround |
|---|---|
| Long point 3 is timed by point 1's time | presets use points 1, 2, 4; `validate_cons` warns when point 3 is active |
| `VHcease` caps the reconnect window even with `VHMflag` off | `VHcease >= VHrecon` in defaults and presets; error otherwise |
| `min(Ipmax, Imax) < Ldfact` starts the load below its power flow | warning |
| Header counts are not checked | the exporter always writes `6 57 8 44 16` |
| Long points above `VLrecon` cycle in a sustained sag | presets raise `VLrecon`; warning |
| `Vtf` must be strictly above `VLrecon` | presets cap `VLrecon` at 0.95 |
| A 0 pu bus returns NaN | as PERC1 standard: noted, not avoidable by CONs |
