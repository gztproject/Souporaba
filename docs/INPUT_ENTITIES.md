# Input entities

This page explains the **canonical input model** used by the Energy Sharing integration. The integration runs on the **receiving household's** Home Assistant instance and reads interval-based energy sources that all describe the **same completed settlement interval**.

## Overview table

| Input | Required | Example |
| Provider export, last interval | Yes | `sensor.trata_solaredge_oddaja_v_omrezje_15min` |
| Receiver import, last interval | Yes | `sensor.hodnik_elektro_stevec_prevzem_iz_omrezja_15min` |
| Allocation percentage | Yes | `input_number.trenutni_odstotek_souporabe` or fixed value |
| Reported allocated energy | No | `sensor.trata_solaredge_gn_souporaba_15min` |

The entity IDs above are **examples only**. You select your real entities in the config flow.

## 1. Provider export interval source (required)

**Semantic name:** `provider_export_source`

**Value used:** `provider_exported_kwh`

This entity represents the **provider household's full energy export to the grid** during the last completed settlement interval, **before** applying any allocation percentage.

Use a Utility Meter or compatible entity that exposes:

- `last_period` — energy exported in the last completed interval
- `last_reset` — timestamp when that interval ended
- `unit_of_measurement` — `kWh` or `Wh`

The integration uses this value **directly** as the authoritative provider export input.

## 2. Receiver grid import interval source (required)

**Semantic name:** `receiver_import_source`

**Value used:** `receiver_imported_kwh`

This entity represents the **receiving household's energy imported from the grid** during the same last completed settlement interval.

It must expose `last_period`, `last_reset`, and `unit_of_measurement` in the same way as the provider export source.

## 3. Allocation percentage (required)

Two mutually exclusive modes are supported:

### A. Entity mode

Select a numeric entity such as `input_number.trenutni_odstotek_souporabe`. Suitable `sensor` or `number` entities are also supported.

**Semantic name:** `allocation_percentage_source`

### B. Fixed mode

Store the percentage directly in integration options.

**Semantic name:** `fixed_allocation_percentage`

The effective percentage used for a processed interval is **persisted with that interval's result**. Seven percent is only a common real-world setting — the integration does not assume 7%.

## 4. Reported allocated energy interval source (optional)

**Semantic name:** `reported_allocation_source`

**Value used:** `reported_allocated_kwh`

Example: `sensor.trata_solaredge_gn_souporaba_15min`

This optional entity reports the allocation calculated or reported by the provider side for the last completed interval. It is used for **reconciliation and diagnostics only**. It is **not** used to reconstruct provider export.

When configured, reconciliation passes if **either**:

- `abs(reported_allocated_kwh - calculated_allocated_kwh) <= allocation_tolerance_kwh`, **or**
- `allocation_difference_pct <= allocation_tolerance_pct`

## Required attributes: `last_period` and `last_reset`

Every required interval source (and the optional reported source when configured) must expose:

| Attribute | Meaning |
|-----------|---------|
| `last_period` | Finite, non-negative energy value for the last completed interval |
| `last_reset` | Parseable ISO timestamp marking the interval boundary |
| `unit_of_measurement` | `kWh` or `Wh` |

### Inspect attributes in Developer Tools → States

1. Open **Developer Tools → States**
2. Search for your entity
3. Confirm the attributes look like this:

```yaml
state: 0.12
attributes:
  last_period: 0.123
  last_reset: 2026-07-12T14:15:00+02:00
  unit_of_measurement: kWh
```

## Supported units: Wh and kWh

All energy values are normalized internally to **kWh**. Unsupported or ambiguous units are rejected with a clear error. The integration never silently assumes an unknown unit is kWh.

## Why full provider export is preferred

Older or simplified setups sometimes try to **reconstruct** provider export by dividing an already allocated energy value by the current percentage (for example, allocated ÷ 7%). That approach is fragile because:

- the percentage may change over time
- allocated values may already include rounding or provider-side logic
- reconciliation becomes impossible

This integration therefore requires the **full provider export interval source** as authoritative input and calculates:

`calculated_allocated_kwh = provider_exported_kwh × allocation_percentage / 100`

## Why all sources must describe the same 15-minute interval

Settlement is performed **once per completed interval**. The integration compares normalized UTC `last_reset` timestamps and uses the reset boundary as a stable interval ID. Values from different intervals are never combined.

With the default 15-minute interval, sources should reset at `:00`, `:15`, `:30`, and `:45`.

## MQTT mirroring

Entities may be local MQTT-mirrored copies of remote provider-household sensors. The integration does not need to know how an entity arrived in Home Assistant, and MQTT transport configuration is **outside** this integration's responsibility.

## Changing source entities later

Provider export and receiver import are identity settings stored in the config entry data. To change them, remove and re-add the integration, or create a new config entry.

Allocation percentage mode, optional reported source, timing, tolerances, and reconciliation behavior can be changed later through the **options flow**.
