# Adding a ride-through preset (development)

Developer notes for the preset library. The user-facing documentation of
every preset is in [`docs/user/presets/`](../user/presets/README.md), which ships
with the app; keep implementation details here instead.

## Adding or editing a preset

**The entire preset library is one Python dict in one file:**
`RIDE_THROUGH_PRESETS` in [`src/presets/ridethrough.py`](../../src/presets/ridethrough.py),
keyed by preset id, each value a `RideThroughPreset` (a plain `@dataclass`).
That is the single place to add a new standard or edit an existing one - no
other file needs to change for the preset to appear in the app:

```python
"your_new_preset": _standard_preset(
    id="your_new_preset",
    label="Shown in the dropdown",
    short_source="Short citation for the model bar and report, e.g. document and table",
    status="Adopted (published)",       # or "Proposed" / "Draft" / etc.
    citation="Full citation - document title, section/table, date, URL if public.",
    envelope=[RideThroughStep(0.50, 0.15), RideThroughStep(0.90, 2.00), RideThroughStep(1.10, None)],
    overvoltage_envelope=[RideThroughStep(1.10, None), RideThroughStep(1.20, 1.00)],
    overcurrent_pu=None,  # or a pu figure if the standard specifies one
    recovery="Plain-English recovery/reconnect requirement, quoted or closely paraphrased from the source.",
    # VDPA/DMA/VDUA/TDUA (stage 1) AND VDPA1-3/DMA1-3/VDUA1-3/TDUA1-3 (stages
    # 2-4) are all DERIVED from envelope/overvoltage_envelope above via
    # multi_stage_undervoltage()/multi_stage_overvoltage() - do not pass any
    # of them directly. Your envelope may have at most 4 mandatory
    # (finite-duration) rows per direction - PERC1's Option-3 table only has
    # 4 stages; a 5th mandatory row raises ValueError, so re-tier/collapse
    # the standard's table if it genuinely has more than 4 real breakpoints.
    # (tdua_override is only needed if overvoltage_envelope has no finite
    # tier - a flat continuous ceiling: tdua_override=0.50.)
    fcease=1.00, vrpa=1.00, tdra=0.0, rampa=1.0, frecon=1.00, npa=0, nqa=0,
    # Optional: ipmaxa=1.0 (current limit), and the standard's frequency table if it
    # publishes one - it sets the block's frequency deadband (FUFTP1/FOFTP1) and is
    # drawn on the live chart:
    # frequency_ride_through=FrequencyRideThrough(
    #     continuous_low_hz=58.8, continuous_high_hz=61.2,
    #     underfrequency=(FrequencyBand(57.0, 299.0),),
    #     overfrequency=(FrequencyBand(61.8, 299.0),),
    #     source="Where the numbers come from."),
),
```

`_standard_preset()` sets `category="Grid operator standard"` automatically and
derives every undervoltage/overvoltage CON - `VDPA`/`DMA`/`VDUA`/`TDUA` and all
3 extra Option-3 stages per direction - from the `envelope`/
`overvoltage_envelope` you pass it (via `_shared_bundle()`) - there is no
separate table to hand-compute or keep in sync. Only the three **generic**
tiers (Extended/Standard/Minimal) need a real IT/VFD distinction (a different
trip delay per block, from docs/user/parameter_tiers.md §1) - those use
`_generic_preset(..., vfd_dma=...)` instead, which derives everything the same
way except that one deliberately-different value (repeated into its own
stages 2-4 too - see `_generic_bundles()`'s docstring). If you're adding a
utility/RTO/ISO standard, you almost certainly want `_standard_preset()`.

Once added:

- It appears in every workflow's "Ride-through preset" dropdown automatically
  (`presets_by_category()` groups by `category` - no UI code changes needed;
  just make sure `category` is one of the two strings `PRESET_CATEGORY_ORDER`
  lists).
- Its voltage and frequency plots can be regenerated with
  `uv run python utils/scripts/generate_envelope_figures.py`.
- Add a matching `docs/user/presets/<id>.md` write-up (copy the
  structure of any existing page in this directory) and the in-app "Preset
  docs" link picks it up automatically too - `ui/main_window.py` looks it up by preset id,
  no code change needed there either.
- Add a row to the library table in `docs/user/presets/README.md`.

See [`docs/developer/PERC1_MODEL.md`](PERC1_MODEL.md) for what each CON in
`it_bundle`/`vfd_bundle` means, and the "Trip fraction, reconnect fraction,
and reconnect timing" section of [the preset overview](../user/presets/README.md) for this library's
conventions on `FCEASE`/`FRECON`/`TDRA`/`RAMPA` when a standard doesn't
specify them directly.

## How the multi-stage table is built in code

`multi_stage_undervoltage()` / `multi_stage_overvoltage()` in
`src/presets/ridethrough.py` build every preset's 4-stage table from its
`envelope`/`overvoltage_envelope` at construction time (called from
`_standard_preset()`/`_generic_preset()`), so the exported CONs cannot drift
from the published table. `collapsed_point()`/`collapsed_overvoltage_point()`
return stage 1, for anything that only needs one number. A flat
continuous overvoltage ceiling (the generic tiers and NERC LLWG SAR) has no
finite tier to derive `TDUA` from, so those presets pass `tdua_override`.
`frequency_trip_points()` collapses a `FrequencyRideThrough` table to the
model's one frequency point per direction. The rules themselves are in the
user page [`docs/user/presets/README.md`](../user/presets/README.md). The
ERCOT fixture validated against the DLL is
`tests/fixtures/multistage_trip/ercot_nogrr282_full_curve_stages.dyr`.

## Regenerating the plots

Every figure embedded in these pages is generated by
`utils/scripts/generate_envelope_figures.py`, which reads directly from
`RIDE_THROUGH_PRESETS` and reuses the exact same envelope-geometry helpers
the live app's tolerance panels use (`envelope_segments_from_steps`,
`overvoltage_segments_from_steps` in `src/presets/envelope.py`):

- `envelope_<id>.svg` - the voltage envelope with **every** exported trip
  stage marked (all four undervoltage and four overvoltage stages, grouped
  and numbered where stages share a point).
- `frequency_<id>.svg` - the block's frequency **deadband** (`FUFTP1` to
  `FOFTP1`, with its trip delays), over the standard's own frequency table
  where the preset has one.

Regenerate after any change to a preset's
`envelope`/`overvoltage_envelope`/`frequency_ride_through`/`it_bundle`:

```bash
uv run python utils/scripts/generate_envelope_figures.py
```

