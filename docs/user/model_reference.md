# PERC1 and PERC2 model reference

This page describes **PERC1** and **PERC2**, the PSS/E dynamic models the app writes for
power-electronics-interfaced load: IT/UPS load and VFD-driven cooling. For
how the model actually behaves when PSS/E runs it, see
[Model behavior and limitations](model_behavior.md). For a side-by-side comparison of
the four models and their PSS/E validation results, see the
[model overview](model_overview.md).

## Which PERC1

PERC1 (Power Electronic Load Model) is based on an electric-vehicle charging
load model developed by EPRI and LBNL. It has two PSS/E implementations, and
**the app writes records for both.** Choose one per block with **PERC1 model
version** at the top of each block's settings; the parameters below it change
with the choice.

| Variant | PSS/E | Supported |
|---|---|---|
| **User-defined model (DLL)**, developed by ISO New England | v34, v35 | **Yes.** 173 CONs, with high- and low-voltage and frequency trip/reconnect, a 4-stage voltage trip table and momentary cessation. |
| **Standard library model** | v36.7 (built in from v36.5) | **Yes.** 30 CONs and one undervoltage cease/reconnect cycle, with droop, voltage exponents and current limits. No overvoltage, frequency or multi-stage trips, so presets that specify those are reduced to their single undervoltage point (the editor says what is left out). |
| **PERC2 DLL v2.3**, developed by ISO New England | v34, v35, v36 (one DLL per version) | **Yes.** The PERC1 DLL with 179 CONs: a reactive-power lead-lag and its own reconnect band and ramps for momentary cessation. Same model name as the PERC1 DLL (`PERCBL`); the header's CON count (179) tells them apart. |
| **PERC2 standard library model** | v36.7 (built in) | **Yes.** 6 on/off flags and 57 CONs: a momentary and a 4-point long cease each for low and high voltage, each with its own reconnect delay and ramp, a low- and high-frequency cease that never reconnects, droop, voltage exponents and current limits with a total-current limit. Presets use their full multi-stage tables (see below). |

The app does not include the DLLs. Load the one that matches the record into
PSS/E as you would any user-defined model, and **only that one**: both DLLs
register `PERCBL`, and PSS/E runs every `PERCBL` record with whichever was
loaded first, without a message. The two standard models need no DLL.

### The PERC2 standard model

PERC2 is chosen like the others, with the model version selector. Its record
is written the same way as the PERC1 standard model's (a main-component
record above it, the same 5 MW / 1.61 / 0.97 pu conditions), with six flags
before the CONs that switch each cease check on or off.

When you pick a preset, the app fills PERC2 from the same values it uses for
the PERC1 DLL: the preset's undervoltage steps become the long low-voltage
table (and a fourth step uses the momentary check), its overvoltage steps
the long high-voltage table, and its frequency trip points the frequency
cease. Three things work differently from PERC1:

- **A frequency cease is permanent.** The load does not come back for the
  rest of the simulation.
- **Each kind of cease has its own reconnect delay and ramp** (momentary,
  long low-voltage, long high-voltage).
- **The ramp time is multiplied by the load factor.** PERC2's `Tramp` of 1.25 s
  with a load factor of 0.8 ramps in 1.0 s; the app converts this for you.

The model has one known PSS/E 36.7.1 problem the app avoids: the third point
of each long table uses the first point's time. The app never uses the third
point. See [Model behavior and limitations](model_behavior.md) for this and
the other behaviors the editor warns about.

### The PERC2 DLL (v2.3)

PERC2 v2.3 is chosen like the others. It writes the PERC1 DLL's record with
six more values (header `12 IT 2 179 33 250 0`) - always 179, although the
DLL's document shows 173: a 173-value record loads silently and, with
momentary cessation on, the load never comes back. Presets fill it from the
same values as the PERC1 DLL, with three adjustments the app makes for you:

- **The voltage reconnect ramps are multiplied by the load factor.** v2.3
  stretches `RAMPA` and `RAMPUA` by `LFM` (the PERC1 DLL does not); the app
  divides them by `LFM` so a preset ramps over the same seconds on both
  DLLs. The frequency and momentary-cessation ramps are not multiplied.
- **The undervoltage reconnect voltage is at most 0.95 pu.** Five presets
  use 1.0 pu, which never reconnects after a recovery to 1.0 pu; the editor
  says when a preset is changed.
- **Momentary cessation stays off.** When you switch it on, the load comes
  back inside its own band (`VLRCMC`-`VURCMC`) after `TBLK` + `TDELY`, ramps
  over `RAMPAMC`/`RAMPUAMC`, and returns only to the reconnect fraction
  (`FRECON`), like after a trip.

Two problems are specific to the PSS/E 36 build (`PERC2_v36_v2p3.dll`): it
stops PSS/E 36.7 when the load comes back from a high-voltage momentary
cessation, and any value in the active-power lead-lag (`TA`/`TB`) makes the
simulation return not-a-number. The editor warns about both. See
[Model behavior and limitations](model_behavior.md).

### The standard model's record

The standard model is a component of PSS/E's composite load, so its record
is written together with a main-component record above it, and PSS/E applies
it only if the load is at least 5 MW, its active-to-reactive ratio is at
least 1.61, and the bus voltage is above 0.97 pu. Keep the delay between
the cease timer and the load reduction (`Tdelay`) at 0: in PSS/E 36.7.1 a
voltage dip that ends during that delay makes the whole simulation return
not-a-number. The editor warns about this and about every value PSS/E would
silently change.

## Model structure

Each power loop (active and reactive) is a chain of blocks:

1. **Washout.** An optional high-pass filter on terminal voltage.
2. **Droop** (active power only). Makes real power follow system frequency;
   `DROOPA = 0` turns it off.
3. **Lead-lag.** Optional transient shaping.
4. **ZIP exponent** (`NPA`/`NQA`). Constant power (0), current (1) or
   impedance (2) as voltage moves.
5. **Current limits** (`IPMAXA`/`IPMINA`/`IQMAXA`/`IQMINA`).
6. **Numerical filter** (`TRA`). A small lag for numerical stability,
   about four times the simulation time step.
7. **Cease and reconnect logic.** Sets the fraction of the block that is
   online, from the filtered terminal voltage and the system frequency.

## Cease and reconnect options

| Option | What it does | In exported records |
|---|---|---|
| **1: Undervoltage cease/reconnect** | One trip voltage and delay, and one reconnect voltage, delay and ramp | **Used.** It is stage 1 of the Option 3 table. |
| **2: Momentary cessation** | Rides through a sag/swell window and resumes after a fixed delay | **Off** (`ICON(M+1) = 0`). Its CONs are written at vendor-typical values. |
| **3: Stepped trip table** | Four voltage stages per direction, each with its own threshold and delay, plus one frequency trip point per direction | **Used.** PSS/E always evaluates all four stages; presets fill them from their published tables. |

**All four voltage stages are always live.** PSS/E testing confirmed that
the DLL has no setting that disables stages 2-4. Every stage times
independently, and whichever reaches its delay first trips the block. A
preset with fewer published tiers repeats its deepest tier into the unused
stages, which cannot cause an earlier trip.

**Frequency has one trip point per direction.** The vendor marks the
stage 2-4 frequency CONs NOT USED, and PSS/E ignores them. The block's
frequency behavior is a deadband: it rides through between `FUFTP1` and
`FOFTP1` and trips once frequency stays outside for `TUFTP1`/`TOFTP1`.

## Which reconnect settings apply to which trip

Each trip path reconnects through its own CONs:

| Trip path | Trip CONs | Reconnect voltage/frequency | Delay | Ramp |
|---|---|---|---|---|
| Undervoltage (all 4 stages) | `VDPA`/`DMA`, `VDPA1-3`/`DMA1-3` | `VRPA` | `TDRA` | `RAMPA` |
| Overvoltage (all 4 stages) | `VDUA`/`TDUA`, `VDUA1-3`/`TDUA1-3` | `VRUPA` | `TRUPA` | `RAMPUA` |
| Under-frequency | `FUFTP1`/`TUFTP1` | `FUFRN1` | `TUFRN1` | `RUFRN1` |
| Over-frequency | `FOFTP1`/`TOFTP1` | `FOFRN1` | `TOFRN1` | `ROFRN1` |

`FCEASE` (the fraction that trips) and `FRECON` (the fraction of that which
reconnects) apply to every path. In PSS/E the reconnect voltage is really a
**window**: both voltage paths reconnect only while `VRPA` < V < `VRUPA`,
and both frequency paths only while `FUFRN1` < f < `FOFRN1`. See
[Model behavior and limitations](model_behavior.md#reconnection-needs-the-voltage-inside-a-window).

Presets set the undervoltage reconnect from their standard's recovery
window. The overvoltage reconnect keeps the vendor-typical 1.05 pu, 5 s and
5 s in every preset, so an overvoltage trip recovers in about 10 s, slower
than the 1-2 s windows the grid-operator presets encode. Edit
**Overvoltage reconnect** in the **Voltage ride-through** row if that matters for your
study.

## Key parameters

Each name below is the model's own CON mnemonic, as shown in the Advanced
editor, the report and the `.dyr` comments.

| CON | Plain name | What it does |
|---|---|---|
| `VDPA`, `DMA` | Vcease, Tcease | Stage 1 undervoltage trip: the block trips after the voltage stays below `VDPA` for `DMA` seconds |
| `VDPA1-3`, `DMA1-3` | | Undervoltage stages 2-4 |
| `VDUA`, `TDUA` (and `1-3`) | | Overvoltage stages 1-4 |
| `VRPA`, `TDRA`, `RAMPA` | Vrecon, Trecon, Tramp | Undervoltage reconnect: voltage, delay, ramp time |
| `VRUPA`, `TRUPA`, `RAMPUA` | | Overvoltage reconnect (`VRUPA` is also the upper edge of the undervoltage reconnect window) |
| `FCEASE`, `FRECON` | Fcease, Frecon | Fraction that trips; fraction of that which reconnects |
| `NPA`, `NQA` | | ZIP exponents for P and Q |
| `IPMAXA`, `IPMINA`, `IQMAXA`, `IQMINA` | | Current limits on the block's MVA base (MW/`LFM`) |
| `LFM` | | The block's power factor, which sets the base of the current limits |
| `DROOPA`, `DBA` | | Frequency droop gain, and its deadband in Hz |
| `TVM`, `TFRQ` | | Filters on the measured voltage and frequency that the trip logic uses |
| `TRA` | Tt | Numerical filter time constant |

The remaining CONs (channels B-D, Option 2 and the unused frequency stages)
are written at vendor-documented values so every record is complete.

## The exported `.dyr` record

Each PERC1 block is a PSS/E `USRLOD` record:

```
IBUS 'USRLOD' 'ID' 'PERC**' 12 IT 2 173 33 250 0
ICON(M) ICON(M+1)
CON(J) ... CON(J+172)   / 173 values, in model order
```

- **Record format** sets the model name suffix and `IT` code:

  | Record format | Model name | `IT` | First field |
  |---|---|---|---|
  | Bus | `PERCBL` | 1 | Bus number |
  | Owner | `PERCOW` | 2 | Owner number |
  | Zone | `PERCZN` | 3 | Zone number |
  | Area | `PERCAR` | 4 | Area number |
  | All | `PERCAL` | 5 | 0 |

  All five forms were confirmed in PSS/E.
- **PERC1 carries no MW or Mvar of its own.** It attaches to an existing
  load in the power-flow case, matched by bus (or subsystem) and load ID.
  The file's comments list each block's approximate MW so you can check it
  against the power-flow load.
- Each row of numbers is labeled with its CON names in an `@!` comment line
  above it, in the same layout as the vendor's example file.

## Conventional cooling motors (optional)

Post-Commissioning can also write a PSS/E `CLOD` record for conventional,
non-VFD cooling motors, in the same record format as the PERC1 blocks. Its
behavior is fixed inside the model; the app sets only its load mix (see
[Generic parameter tiers](parameter_tiers.md#3-optional-conventional-cooling-motors-clod)).
