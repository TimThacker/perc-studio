# Model overview and comparison

The app writes, imports, previews and reports on **four PSS/E load models** for
power-electronics-interfaced load. They descend from one model (PERC1) but differ in what
they can represent, which PSS/E versions run them, and what they need installed. This page
compares them side by side; each has its own page with the PSS/E validation results and
plots behind it.

| Model | Page |
|---|---|
| **PERC1 DLL**: ISO New England's user-defined model, 173 CONs | [PERC1 DLL](model_perc1_dll.md) |
| **PERC1 standard**: Siemens' built-in model, 30 CONs | [PERC1 standard](model_perc1_standard.md) |
| **PERC2 standard**: Siemens' built-in successor, 6 flags and 57 CONs | [PERC2 standard](model_perc2_standard.md) |
| **PERC2 DLL v2.3**: ISO New England's DLL, 179 CONs | [PERC2 DLL v2.3](model_perc2_dll.md) |

You choose one per block with **PERC1 model version** at the top of each block's settings.
For what each CON means, see the [model reference](model_reference.md); for the behaviors the
editor warns about, see [Model behavior and limitations](model_behavior.md).

## At a glance

| | PERC1 DLL | PERC1 standard | PERC2 standard | PERC2 DLL v2.3 |
|---|---|---|---|---|
| **Developed by** | ISO New England | Siemens (library model) | Siemens (library model) | ISO New England |
| **PSS/E versions** | 34 and 35 | 36.5 and later (built in) | 36.7 (built in) | 34, 35 and 36, one DLL per version |
| **Validated on** | 35.6.4 | 36.7.1 | 36.7.1 | 35.6.4 and 36.7.1 |
| **Needs a DLL** | Yes (`PERC2_V35.dll`) | No | No | Yes (`PERC2_v35_v2p3.dll` or `PERC2_v36_v2p3.dll`) |
| **Needs a main-component record** | No | Yes (`MAINxx10`) | Yes (`MAINxx10`) | No |
| **PSS/E model name** | `PERCBL` and the other four scopes | `PERCxx1U` | `PERCxx2U` | `PERCBL`, same name as the PERC1 DLL |
| **Record** | `USRLOD`, 173 CONs | `USRLODC`, 30 CONs | `USRLODC`, 6 flags and 57 CONs | `USRLOD`, 2 ICONs and 179 CONs |
| **Applied only if** | always | load ≥ 5 MW, P/Q ≥ 1.61, bus above 0.97 pu at start | same as PERC1 standard | always |

## What each model can represent

| | PERC1 DLL | PERC1 standard | PERC2 standard | PERC2 DLL v2.3 |
|---|---|---|---|---|
| **Undervoltage cease** | 4 stages, each with a threshold and a delay | 1 point | momentary check plus a 4-point long table | 4 stages |
| **Overvoltage cease** | 4 stages | none | momentary check plus a 4-point long table | 4 stages |
| **Frequency cease** | 1 under- and 1 over-frequency point, reconnects | none | under- and over-frequency, **never reconnects** | 1 under- and 1 over-frequency point, reconnects (60 Hz only) |
| **Momentary cessation** | Option 2 (off in exported records) | no separate mode | flags, per kind of cease | Option 2, with its own reconnect band and ramps |
| **Reconnect after a trip** | voltage window and timer per direction, ramp | one voltage, one timer, one ramp | own delay and ramp for each kind of cease | as the PERC1 DLL, with the ramps scaled by the load factor |
| **Frequency droop** | `DROOPA`, `DBA`; always on | `Kdroop`, deadband | yes | as the PERC1 DLL |
| **Voltage exponents** (constant power, current, impedance) | `NPA`, `NQA` | `nP`, `nQ` | yes | `NPA`, `NQA` |
| **Current limits** | P and Q separately | P and Q separately | plus a total-current limit | P and Q separately |
| **Reactive lead-lag** | no | yes | yes | yes (`TAQ`/`TBQ`) |

Ride-through presets use what the model offers. Presets that specify overvoltage, frequency
or several voltage steps are written in full for the PERC1 DLL, the PERC2 DLL and PERC2
standard. For PERC1 standard they are reduced to the single undervoltage point the model has,
and the editor says what is left out.

## What to watch for in each

These are the behaviors found in PSS/E that matter most in a study. The editor warns about
each one it can; the details and plots are on each model's page.

| | PERC1 DLL | PERC1 standard | PERC2 standard | PERC2 DLL v2.3 |
|---|---|---|---|---|
| **Reconnect needs** | voltage strictly inside `VRPA`-`VRUPA` | voltage above `Vrecon` | voltage inside the reconnect window | voltage inside the window; momentary cessation has its own |
| **Preset trap** | five presets with `VRPA` = 1.0 never reconnect | `Vrecon` of 1.0 strands the load | none found | same `VRPA` cap as the PERC1 DLL |
| **Returns not-a-number when** | `TA` without `TB` | a dip ends during `Tdelay` (some of the time); bus at exactly 0 pu | bus at exactly 0 pu | `TA` or `TAQ` without its `TB`; **any** `TA`/`TB` on the v36 build |
| **Stops PSS/E** | no | no | no | **the v36 build, when a high-voltage momentary cessation ramp ends** |
| **Silent surprises** | both DLLs share `PERCBL`: the first one loaded runs every record | values are clamped with no message | third long-table point uses the first point's time | a 173-value record loads, then a ceased load never returns |
| **Ramp after a dip** | a new dip during a ramp trips again | same | same | same |

Every one of these was reproduced in PSS/E and is guarded by a check in the editor, the
report or the live chart.

## How much validation sits behind each model

Every model was run in the real PSS/E, never only in the app's own simulator. The app's live
chart is then compared with the PSS/E traces.

| | PERC1 DLL | PERC1 standard | PERC2 standard | PERC2 DLL v2.3 |
|---|---|---|---|---|
| **PSS/E runs** | 840 preset tests and 198 targeted probes | 435 cases | 443 cases | 285 cases on 35.6.4 and 194 on 36.7.1 |
| **Automatic checks** | 744, all pass | 262, all pass | 609, all pass | 351, all pass |
| **Reference** | vendor manual | Siemens model library, section 13.6 | Siemens' data sheet for the model | the vendor document and its sample record |
| **Live chart vs PSS/E** | voltage trips within about 12 ms; same reconnect outcomes | cease and reconnect timeline, exponents and droop reproduced | cease/reconnect sequence reproduced in every comparable case | first cease, ramp start and ramp length matched in all 79 single-dip cases |
| **Every preset exported by the app was run in PSS/E** | yes | yes | yes | yes (a representative set) |

The PSS/E runs behind these counts are in the authors' PSS/E validation library, which is not published.

## Which to choose

- **Your PSS/E is 34 or 35:** the PERC1 DLL or the PERC2 DLL v2.3. Only the DLLs exist there.
- **Your PSS/E is 36.7 and you do not want a DLL:** PERC2 standard, which has the full
  ride-through tables. PERC1 standard keeps to one undervoltage cease and reconnect cycle.
- **You need momentary cessation or a reactive lead-lag with a DLL:** PERC2 DLL v2.3.
- **You need a frequency trip that reconnects:** the PERC1 DLL or the PERC2 DLL. PERC2
  standard's frequency cease is permanent, and PERC1 standard has none.
- **Your network is 50 Hz:** neither DLL works as documented. Both measure frequency against
  60 Hz whatever the model's 50 Hz flag says.
- **Your team's study must match NERC's Level 3 Alert baseline:** PERC1, either variant, is
  the model it names; PERC2 is the newer, more capable one.

Never load both DLLs in one PSS/E session: both register `PERCBL`, and PSS/E runs every
`PERCBL` record with whichever it loaded first, without a message.
