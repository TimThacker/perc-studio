# Getting started

PERC Studio accelerates data center modeling for transmission planning
engineers. It builds documented PSS/E dynamic load models for a large,
power-electronics-heavy load such as a data center, across several load models
(the PERC1 and PERC2 variants today). You choose a model, a ride-through
standard or tier, adjust the model if you have better data, and watch the
simulated response update as you go. The app then writes:

- a **`.dyr` file** with records in the exact CON layout of the vendor model;
  and
- an **HTML report** that records every assumption, the parameter values,
  the preset's citation and the response plots, for review or a study file.

The app does not include PSS/E or the model DLLs. You need PSS/E (and, for
the DLL variants, the DLL) to run the exported `.dyr` file in a study.

## Install and launch

Windows 10 or 11 (64-bit). No administrator rights and no internet
connection are needed.

- **Installer:** run `PERC-Studio-<version>-Setup.exe`. It installs
  for your user account only and adds a desktop shortcut and a Start-menu
  entry.
- **Portable ZIP:** extract `PERC-Studio-<version>-win64.zip`
  anywhere, then double-click **Create Desktop Shortcut.cmd** once. You can
  also run `PERC Studio.exe` from the extracted folder directly.

Launch the app from the **PERC Studio** desktop shortcut.

## The window

The tabs along the top of the window:

| Tab | Use it for |
|---|---|
| **Screening** | A quick, single-block estimate: name the load, give its bus and size, pick a ride-through preset, export. |
| **Post-Commissioning** | A full facility, with separate blocks for IT/UPS and cooling VFD load and every parameter editable. |
| **Documentation** | This library. **Preset docs** beside any preset opens that preset's page here. |

The pill at the top right shows the app version. The footer carries the
engineering-tool notice.

## Screening

1. **Model** (the bar along the top). Choose the **PERC1 model version**
   (DLL for PSS/E 34/35, or the PSS/E 36.7 standard model), the **PSS/E
   record** format (Bus, Owner, Zone, Area or All) and a **Ride-through
   preset**. The badge beside the preset says where it comes from:
   **Internal** for the three generic tiers (Extended, Standard, Minimal,
   internal engineering judgments) and **Published standard** for the
   grid-operator standards (see [Preset library overview](presets/README.md)).
   Hover over the preset for its source and full citation; **Preset docs**
   opens its page.
2. **1 · Load.** Enter the facility name, load ID, bus number and name, and
   the active and reactive power of the load. Owner, Zone and Area records
   also ask for that number.
3. **2 · Parameters.** One row per group of parameters, each with a short
   summary of its values (for example `UV 0.70 pu · 0.02 s`). Click a row to
   open its fields. Edited rows are shaded and bold, and the count shows how
   many parameters differ from the preset ("2 edited"). **Reset to preset**
   is available once something is edited; **Revert this row** inside a row
   undoes just that row.
4. **Export.** **Save .dyr…** writes the model; **Save report…** writes a
   short PERC1 screening report (the load, the preset and its citation, the
   parameters, the response plots and the `.dyr` text). **View .dyr** shows
   the record text.

Choosing another preset, importing another file or changing the model
version while parameters are edited asks before discarding the edits.

### Inspecting an existing `.dyr`

**Import .dyr…** (at the right of the model bar, on every block) loads a PERC1 record from a
`.dyr` file so the live chart shows what the file's model does before you simulate it.

- The model version switches to the file's (PERC1 DLL or PERC1 standard), and every
  parameter appears in the editor. The preset field is replaced by the **Imported file**
  name, and the chart has no preset envelope to compare against.
- If the file holds several records, a list asks which one to load. CLOD records are
  listed but cannot be inspected.
- A value outside the editor's usual range is kept as written and flagged under the
  fields; it is not clamped.
- Edits are shown against the file's values. The exported record uses the
  file's parameters plus your edits. The record format and load ID come from the
  app's settings, not from the file.
- **Reset to file** returns to the file's values and keeps the file.
  **Use a preset instead** (or choosing a preset) replaces the imported record.

Screening results are labeled as placeholders in the report until they are
replaced with vendor or field-validated values.

## Post-Commissioning

The steps run along the top, each with its block's MW; the bar at the right
shows the load split.

1. **Site.** Facility, bus, total load and the percentage split across
   IT / UPS, cooling VFD, CLOD motors and other load. The split must total
   100%. Record format and each block's load ID are set here too.
2. **IT / UPS** and **VFD.** The strip under the steps sets **Model for this
   block**: each block can use its own PERC1 version, with its own preset or
   imported file (the same controls as on Screening). The panel on the left
   sets the **Operating mode** (UPS type or VFD front end, which sets the
   ZIP exponents) and the parameter rows:
   - **Voltage ride-through:** all four undervoltage and four overvoltage
     trip stages, and each direction's reconnect settings.
   - **Frequency ride-through:** the frequency deadband, trip delays and
     reconnect settings.
   - **Trip / reconnect fractions**, **ZIP exponent**, **Current limits**
     and **Other** (`DROOPA`, `TRA`).

   Hover over any parameter label to see its CON name. Under the charts,
   **Facility response to this event** shows how every block responds to
   the same event.
3. **CLOD motors.** Only if the facility has conventional, non-VFD cooling
   motors: sets their share of a PSS/E CLOD motor-load record.
4. **Review & export.** A card per block (model, preset or file, edits, MW)
   and every exported value, with **Save .dyr…** and **Save report…** (the
   full facility report: facility summary, load composition and every
   block).

## Reading the live chart

Each PERC1 block (and the Screening block) has a live chart on the right that
updates as you change anything.

- Choose **Voltage event** or **Frequency event**.
- The sliders set the event: **duration** (in cycles for a voltage event,
  seconds for a frequency event) and **depth** (a positive depth is a sag, a
  negative depth a swell; for frequency, the offset from 60 Hz).
- The verdict strip above the charts says **TRIPS** or **RIDES THROUGH**,
  when the block trips and reconnects, and the load tripped, the load
  reconnected and the ramp time.
- **Voltage at the load bus** (or frequency, for a frequency event) shows the
  event with the block's trip and reconnect thresholds. **Power output**
  shows the fraction of the block's power online, with a strip underneath
  marking when it is online, ceased (and what fraction ceased) and
  reconnecting.
- **Voltage vs. standard** places every trip stage and the event on the
  selected preset's ride-through envelope: the result ("Both stages OK"),
  and whether the event falls where the preset permits a trip. For a
  frequency event it uses the preset's frequency table, or says the preset
  has none.
- Zoom and pan with the chart toolbar. Changing a slider keeps your zoom.

**The live chart is a fast simulation of the model, not PSS/E.** It follows
the rules measured in PSS/E: the filtered-voltage trip timing, the reconnect
window, frequency droop and the current limits. Its event recovers to exactly
nominal, so a preset with `VRPA = 1.00` stays tripped there. Read
[Model behavior and limitations](model_behavior.md) for what each rule means
for a study.

## Before using a model in a study

- Confirm the preset's numbers against the entity's current primary
  document. Each preset page lists its exact source.
- Check the load bus voltage in your power-flow case. Some presets trip at a
  steady voltage at their continuous limit (see
  [Model behavior and limitations](model_behavior.md#check-the-operating-voltage-first)).
- Review `VRPA` for the grid-operator presets. With the shipped
  `VRPA = 1.00`, a block reconnects in PSS/E only if the voltage settles
  above 1.00 pu.
- Replace placeholder values with vendor or field-validated data where you
  have it.

## Feedback and support

Questions, bug reports and suggestions are welcome on the project's
[GitHub Issues](https://github.com/TimThacker/perc-studio/issues) page. Include the version shown on the **About** page and, for a
problem, the steps that led to it and the saved `.dyr` file or report.
