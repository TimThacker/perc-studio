# Under development and future work

## In progress

| Feature | What it will do |
|---|---|
| **Modular CMLD motor load** | The modular composite load model (CMLD) as an option beside CLOD for the motor share of a facility. |
| **Faster black-box validation** | A shorter validation run, by reusing PSS/E processes and keeping every worker busy. |
| **Full-facility testing in a real system** | Upload a PSS/E case and test a whole facility, several load models together that represent a data center, in that system. |

## Future work

Known gaps and planned improvements. The first two are described in detail
in [Model behavior and limitations](model_behavior.md).

- **Review preset defaults against the PSS/E findings:**
  - `VRPA` for the five presets that ship with `VRPA = 1.00` (ERCOT, PJM,
    MISO, NERC LLWG SAR, NERC PRC-029-1);
  - `DROOPA` per preset, where a standard asks for constant consumption
    during frequency events;
  - overvoltage reconnect timing (`TRUPA`/`RAMPUA`) to match each standard's
    recovery window.
- **Editor warnings** when `VRPA` is below a trip stage (the block cycles),
  `VRPA` ≥ `VRUPA` (never reconnects), or `IPMAXA` < `LFM` (the block
  cannot draw its own load).
- **Recovery voltage in the live chart.** A control for the voltage (or
  frequency) the event recovers to, to show a `VRPA` window or a cycling
  block directly. The simulator already supports it.
- **Multi-event disturbances in the live chart:** sags that change depth,
  or recover briefly and return, with the model's resetting stage timers.
- **Standard-model refinements:** washout and lead-lag transients in the live
  chart.
- **Keep the PERC2 warnings current.** The PSS/E validation found issues in the PERC2 models that their
  authors may fix or document (see each model's validation page). The editor's warnings will be
  revisited when new versions of PSS/E or the DLL appear.
- **Parameterize load models from PSCAD benchmark performance.** Derive model
  parameters from how a PSCAD model performs against a benchmark.
- **More load models**, and more ride-through standards as utilities and
  NERC publish them.
- **Out-of-sample PSS/E validation** on randomized scenarios.

Suggestions for this list are welcome on the project's
[GitHub Issues](https://github.com/TimThacker/perc-studio/issues) page.
