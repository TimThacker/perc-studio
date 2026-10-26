# Ride-through preset library

Every entry in the app's **Ride-through preset** dropdown has its own page
here, with the same structure: what the standard requires, where the numbers
came from, plots of the voltage and frequency envelopes, and exactly how the
app maps it onto the exported model's CON values.

**If you support a utility, RTO or ISO with a published or proposed
large-load ride-through requirement, start with that entity's page.** Each
page is meant to be a citation trail you can hand to a colleague or a
regulator.

## The preset library

| Preset | Category | Status | Doc |
|---|---|---|---|
| Extended (ITI/CBEMA-plus) | Generic | Adopted (internal) | [extended.md](extended.md) |
| Standard (ITIC/CBEMA) | Generic | Adopted (internal) | [standard_itic.md](standard_itic.md) |
| Minimal / unknown | Generic | Adopted (internal) | [minimal.md](minimal.md) |
| SPP (HILL ride-through curve) | Grid operator standard | Adopted (published) | [spp_hill.md](spp_hill.md) |
| ERCOT (NOGRR282) | Grid operator standard | **Adopted (PUCT-approved)** | [ercot_nogrr282.md](ercot_nogrr282.md) |
| PJM (LCL proposal) | Grid operator standard | Proposed | [pjm_lcl.md](pjm_lcl.md) |
| MISO (draft) | Grid operator standard | Draft | [miso_draft.md](miso_draft.md) |
| NERC LLWG SAR (pre-standard proposal) | Grid operator standard | Proposed (pre-standard) | [nerc_llwg_sar.md](nerc_llwg_sar.md) |
| NERC PRC-029-1 (IBR reference) | Grid operator standard | **Adopted (FERC-approved)**, generator/IBR-side | [nerc_prc029.md](nerc_prc029.md) |

"Adopted" here means the cited entity has formally adopted or published the
requirement (PUCT-approved guide language, a filed/published requirements
document, or a Board-adopted, FERC-approved NERC Reliability Standard) — not
that this app's transcription/parameterization of it has been independently
audited by that entity. Always confirm against the entity's own current
primary document before using a preset's numbers in a compliance filing or a
final planning study; the "Primary source" section of each page gives you
the exact document to check.

## Why these numbers, and not ITIC/CBEMA

Every preset here is an **independently-sourced, self-contained** set of
voltage/duration breakpoints, transcribed from that entity's own published
chart or table. None of them are derived from, or benchmarked against, the
ITIC (CBEMA) curve — the widely-used 1970s-era equipment power-quality
tolerance curve from the Information Technology Industry Council (formerly
the Computer & Business Equipment Manufacturers Association). ITIC describes
what sag/swell durations a piece of indoor IT hardware's power supply should
ride through without malfunctioning; it was never a bulk-power-system
reliability standard, no grid operator or NERC standard cites it as an
interconnection compliance target, and it does not appear anywhere in the
industry's own comparison materials for these requirements (see below). This
app's live response plot and this documentation compare a facility's
configured trip point only against the *selected preset's own* envelope, on
both the undervoltage and overvoltage side — never against ITIC.

This matters in practice: ERCOT's, SPP's, and MISO's own continuous-operating
floors (0.90 pu) all take effect well before ITIC's does (2.0 s vs. ITIC's
10 s) — so a facility that just barely clears one of these standards can
still sit briefly *outside* the ITIC curve in that narrow window. That is not
an error in either the standard or this app; it is a real, independently
confirmed property of ERCOT/SPP/MISO's own filed numbers. It just means ITIC
is the wrong yardstick to compare any of these standards against — the actual
industry comparison baseline the standards bodies use for load curves is
**NERC PRC-029-1** (generator/IBR ride-through, adopted and FERC-approved),
which is exactly why PRC-029-1 is in this library too (see
[nerc_prc029.md](nerc_prc029.md)) — not because a data center load is bound by
a generator standard, but because it's the actual benchmark PJM's own
proposal deck uses when comparing ERCOT/MISO/NERC LLWG SAR against each
other.

## How a multi-tier standard becomes a full multi-stage PSS/E CON table

Most standards publish a **table** of ride-through requirements, not one
point. ERCOT NOGRR282, for example, requires riding through 0.20 pu for
0.15 s, 0.50 pu for 0.25 s, 0.80 pu for 0.50 s, 0.90 pu for 2.00 s, and
continuously above that. PERC1 has a **4-stage trip table per direction**
(`VDPA`/`DMA` plus `VDPA1-3`/`DMA1-3` for undervoltage, `VDUA`/`TDUA` plus
`VDUA1-3`/`TDUA1-3` for overvoltage), and PSS/E testing confirmed that the
model **always evaluates all four stages** (see
[Model behavior and limitations](../model_behavior.md#the-multi-stage-trip-table-works-as-published)).
So every preset exports its standard's full table:

> **Take every mandatory (finite-duration) row, excluding the continuous
> operating floor or ceiling, sorted shallowest first. Map up to four of them
> onto stages 1-4, in order.**
>
> **Undervoltage, if fewer than four rows exist:** repeat the deepest row into
> the remaining stages. A repeated stage trips at exactly the same time as the
> row it copies, so it cannot cause an earlier trip.
>
> **Overvoltage:** no standard here publishes more than one mandatory
> overvoltage tier, and those that address it say what ERCOT says explicitly:
> "above 1.20 pu: may ride through or trip." A row like ERCOT's "up to
> 1.20 pu: tolerate for at least 2.0 s" covers the whole band above the
> continuous ceiling (1.10 pu), so **stage 1 arms at the continuous ceiling
> (1.10 pu) with the tier's duration (2.0 s)**. Stages 2-4 arm at the
> tier's own voltage (1.20 pu) with no delay, so anything above the tier trips
> immediately. Every voltage and duration used is one of the standard's own
> published numbers.

**Worked example (ERCOT NOGRR282, undervoltage).** The table's five rows are
four mandatory tiers plus the continuous floor. The four tiers map onto the
four stages, highest voltage first: `VDPA=0.90`/`DMA=2.00`,
`VDPA1=0.80`/`DMA1=0.50`, `VDPA2=0.50`/`DMA2=0.25`,
`VDPA3=0.20`/`DMA3=0.15`. That is ERCOT's Table A exactly, and it is the
record validated in PSS/E.

**A flat overvoltage ceiling.** The three generic tiers and NERC LLWG SAR
publish only a continuous ceiling ("continuous up to X pu") with no finite
tier. PERC1 still needs a finite `TDUA`, so those presets use a chosen value,
explained on each preset's page, and fill stages 2-4 the same way as every
other preset.

Each preset page shows its published table next to the exported stages, so
you can check that they match.

## Frequency ride-through

A preset carries a frequency table only where its source publishes a
complete one: a continuous band, plus rows outward from it, each with a
limit and a minimum ride-through time.

| Preset | Table |
|---|---|
| PJM (LCL proposal) | 58.8-61.2 Hz continuous; 299 s down to 57.0 Hz / up to 61.8 Hz |
| NERC PRC-029-1 | Same numbers, from Attachment 2, Table 3 |

SPP (a 58.8-61.2 Hz continuous band only), MISO (a 57.5-61.2 Hz band) and
ERCOT (asymmetric limits without durations) are recorded on their own pages
but are not complete enough to encode. Those presets, like the generic tiers,
keep PERC1's vendor-typical frequency settings: trip below 58.0 Hz or above
62.0 Hz after 100 s.

PERC1 has **one** frequency trip point per direction (the vendor marks the
other frequency stages NOT USED, and PSS/E ignores them). A table is
therefore collapsed to one point: arm at the edge of the continuous band with
the innermost row's duration (for PRC-029-1, below 58.8 Hz or above 61.2 Hz
for 299 s). That never trips where the table requires riding through, and
beyond the outermost row it rides through longer than required, which is
always compliant. Reconnect is at the band's edge with the vendor's 100 s
delay and 5 s ramp, since none of these sources publish frequency reconnect
timing. The live chart's frequency panel plots the table, the block's trip
point in each direction and where a simulated frequency event lands.

## Trip fraction, reconnect fraction, and reconnect timing (`FCEASE`/`FRECON`/`TDRA`/`RAMPA`)

A ride-through envelope only says *when* a block is allowed to trip - it
says nothing about *how much* of the facility trips, *how much* of that
comes back, or *how fast*. Those four fields are PERC1's own `FCEASE`,
`FRECON`, `TDRA` (Trecon), and `RAMPA` (Tramp) CONs, and each grid-operator
standard's own text was checked for whether it actually specifies them.
Full reasoning and citations are in each preset's own "Reconnection
behavior" section; this table is the cross-standard summary:

| Preset | Trip fraction (`FCEASE`) | Reconnect fraction (`FRECON`) | Reconnect delay (`TDRA`) | Ramp rate (`RAMPA`) | Combined window |
|---|---|---|---|---|---|
| [SPP HILL](spp_hill.md) | Not standardized - app default (1.00) | Not standardized - app default (1.00) | Not standardized - app default (0.0 s) | **Standardized: 0.083 s** (5 cycles) | 0.083 s, ≥90% within |
| [ERCOT NOGRR282](ercot_nogrr282.md) | Not standardized - app default (1.00) | Not standardized - app default (1.00) | App-derived split (0.917 s) | **App's ramp-rate benchmark: 0.083 s** | 1.0 s, ≥90% within (standardized) |
| [PJM LCL](pjm_lcl.md) | Not standardized for IT; VFD full-trip is an explicit PJM allowance - app default (1.00) | Not standardized - app default (1.00) | App-derived split (1.917 s) | **App's ramp-rate benchmark: 0.083 s** | 2.0 s, ≥90% within (standardized) |
| [MISO draft](miso_draft.md) | Not standardized - app default (1.00) | Not standardized - app default (1.00) | App-derived split (0.917 s) | **App's ramp-rate benchmark: 0.083 s** | 1.0 s, ≥90% within (standardized) |
| [NERC LLWG SAR](nerc_llwg_sar.md) | Not specified anywhere - app default (1.00) | Not specified anywhere - app default (1.00) | Not specified anywhere - app default, ERCOT-derived split (0.917 s) | **App's ramp-rate benchmark: 0.083 s** | 1.0 s, not specified anywhere - borrowed from ERCOT |
| [NERC PRC-029-1](nerc_prc029.md) | Not applicable (IBR curtailment, not a load "cease" concept) - app default (1.00) | Not specified - app default (1.00) | App-derived split (0.917 s) | **App's ramp-rate benchmark: 0.083 s** | 1.0 s, 100% within (standardized, exact match - the only preset with a 100%, not ≥90%, figure) |

Three patterns worth calling out:

- **None of these standards specify a discrete trip fraction or reconnect
  fraction.** Where they address load behavior during a disturbance at all,
  it's as *continuous, voltage-proportional curtailment* ("may reduce active
  power proportional to the voltage drop"), which PERC1's Option 1
  cease/reconnect logic cannot represent - it only has a binary "this
  fraction ceases entirely" (`FCEASE`) concept. `FCEASE=1.00`/`FRECON=1.00`
  (full trip, full reconnect) is this app's consistent approximation across
  every preset in this library, not a per-standard result - see each page's
  "Known caveats" section.
- **`TDRA` (reconnect delay) and `RAMPA` (ramp rate) are two distinct CONs,
  and every standard that specifies recovery timing at all only gives one
  combined window** ("restore ≥90% within N seconds of voltage recovery"),
  not a "confirm, then ramp" split. Modeling that entire window as `RAMPA`
  (a slow linear ramp) would conflate the two concepts and produce an
  implausibly slow, seconds-long power swing for equipment that is, by
  construction, power-electronics-interfaced. Instead, this app fixes
  `RAMPA=0.083 s` (5 cycles - SPP's own published figure, the one standard
  here that actually specifies a plausible power-electronics ramp rate
  directly, reused as this app's general benchmark) as a realistic ramp
  duration, and allocates the remainder of each standard's window to `TDRA`
  as a confirmation/dwell delay before the ramp starts. The combined total
  (`TDRA+RAMPA`) still reaches the standard's own restoration percentage by
  its own deadline - at least as fast as required, never slower (NERC
  PRC-029-1 is the sole exception, where the source itself specifies 100%,
  making this an exact match rather than a conservative one).
- **NERC LLWG SAR is the only preset with no recovery timing published at
  all.** Its combined window (and therefore its `TDRA`/`RAMPA` split) is
  borrowed from ERCOT NOGRR282 (see [nerc_llwg_sar.md](nerc_llwg_sar.md)) as
  the most defensible available industry figure, not a NERC number.

## Related documentation

- [Generic parameter tiers](../parameter_tiers.md): where the three generic
  tiers' numbers come from.
- [PERC1 model reference](../model_reference.md): what `VDPA`, `DMA`,
  `VRPA`, `VDUA`, `IPMAXA` and the other CONs do.
- [Model behavior and limitations](../model_behavior.md): how PSS/E runs
  these presets, including the `VRPA = 1.00` reconnect caveat for five of
  them.
