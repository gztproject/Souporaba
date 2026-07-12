# Input entities

The Energy Sharing integration **no longer requires Utility Meter helpers** or entities that expose `last_period` and `last_reset`.

Instead, it reads **cumulative energy counters** and creates aligned 15-minute settlement intervals internally on the receiving household Home Assistant instance.

## Overview table

| Input | Required | Meaning |
| Receiver total grid import | Yes | Cumulative energy imported by the receiving household |
| Total received shared energy | Yes | Cumulative energy allocated to the receiver |
| Fixed allocation percentage | Conditional | Required when provider export is not supplied |
| Provider total grid export | Conditional | Full cumulative exported surplus of the provider |

**At least one** of fixed allocation percentage or provider total grid export must be configured.

Example entity IDs (not hard-coded):

| Role | Example |
| Receiver total grid import | `sensor.hodnik_elektro_stevec_prevzem_iz_omrezja` |
| Total received shared energy | `sensor.trata_solaredge_gn_souporaba_skupaj` |
| Provider total grid export | `sensor.trata_solaredge_skupna_oddana_energija` |
| Fixed allocation percentage | `7.0` in integration options |

## Operating modes

### A. Percentage-only mode

**Inputs:** receiver total import, shared energy total, fixed allocation percentage.

Provider interval export is **inferred**:

`inferred_provider_export = shared_interval / (fixed_percentage / 100)`

This value is labeled **inferred**, not directly measured.

### B. Export-only mode

**Inputs:** receiver total import, shared energy total, provider total export.

Settlement uses measured provider export deltas. The contractual percentage is not configured, but an **effective allocation percentage** can be calculated when provider export is greater than zero.

### C. Export + percentage mode (preferred)

**Inputs:** receiver total import, shared energy total, provider total export, fixed allocation percentage.

Provider export is the authoritative measured export. Expected shared energy is:

`expected_shared = provider_export_interval × fixed_percentage / 100`

The integration compares this with the actual shared-energy interval derived from the cumulative shared-energy counter. This mode supports the strongest reconciliation and diagnostics.

## Expected source properties

Each cumulative source should provide:

- a numeric, non-negative state;
- `unit_of_measurement` of `kWh` or `Wh`;
- normally monotonic increasing under normal operation.

The integration validates by semantics and unit, not only by metadata such as `device_class` or `state_class`.

Entities may be MQTT-mirrored from a remote Home Assistant instance. MQTT transport is outside this integration's responsibility.

## Internal 15-minute interval engine

The integration aligns intervals to wall-clock boundaries (`:00`, `:15`, `:30`, `:45` for 15-minute intervals).

At each boundary plus the configured processing delay:

1. Read cumulative source totals.
2. Compare them with persisted boundary snapshots.
3. Calculate interval deltas.
4. Calculate settlement values.
5. Persist snapshots and results atomically.

### First setup

The **first valid boundary establishes a baseline only**. No energy is added to integration-owned cumulative totals for that partial interval. Status: `initializing_baseline`.

### Counter resets

If a cumulative counter decreases, the integration treats this as a **counter reset or source replacement**:

- the affected interval is skipped;
- a new baseline is established from the current readings;
- integration-owned cumulative totals are **not** decreased.

### Skipped intervals and snapshots

Raw source snapshots **always advance** at every valid boundary read, even when settlement is skipped. This prevents a skipped interval from being merged into the next interval.

Reconciliation `skip_interval` mode skips accumulation of settlement totals but still advances raw snapshots.

### Limitations

Without a source-provided measurement timestamp on the cumulative entities, exact boundary attribution depends on how quickly the source entities update after each boundary. Optional timestamp attribute names can be configured in the options flow.

Missed historical intervals cannot always be reconstructed when only the latest cumulative reading is available.

## Reconciliation (export + percentage mode)

Reconciliation passes when **either**:

- `abs(shared - expected_shared) <= allocation_tolerance_kwh`, **or**
- `allocation_difference_pct <= allocation_tolerance_pct`

Failure modes:

- **warn** — process using actual shared-energy delta and record a warning;
- **skip_interval** — do not add the interval to cumulative settlement totals.

## Optional timestamp attributes

For advanced setups, you may configure an attribute name that contains the source measurement timestamp, for example `meter_timestamp` or `reading_time`. These are optional and not required for initial setup.

## Changing sources

Receiver total import and shared energy total are identity settings in the config entry. Changing them requires removing and re-adding the integration, or using a dedicated reconfigure flow if available.

Provider export source, fixed percentage, timing, tolerances, and timestamp attributes can be changed in the options flow. After major source changes, use **Reinitialize baseline** if needed.
