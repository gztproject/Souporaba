# Energy Sharing

Home Assistant custom integration that calculates **solar energy sharing settlement** between two households.

The energy provider exports surplus solar energy to the grid. A configurable percentage of that exported energy is contractually allocated to the receiving household. This integration performs settlement **independently for every completed 15-minute interval** on the receiving Home Assistant instance.

> **Important:** Shared energy is an **accounting allocation through the grid**, not locally generated solar energy at the receiving household. Interval energy sensors describe settlement results, not physical on-site production.

## What this integration does

For each completed 15-minute interval, the integration reads:

1. Receiving household **grid import** from a Utility Meter
2. **Allocated shared energy** from a Utility Meter
3. **Allocation percentage** from an entity or a fixed configured value

It then calculates:

- inferred provider export
- used / unused shared energy
- billable grid energy
- required and ideal allocation percentages
- utilization and coverage percentages
- cumulative totals suitable for long-term statistics and Utility Meter helpers

Processing happens **once per completed interval**, shortly after each quarter-hour boundary. It does not recalculate on every source entity change.

## 15-minute settlement model

Utility Meter helpers reset at interval boundaries (`:00`, `:15`, `:30`, `:45`). After a boundary, they expose the completed interval value in the `last_period` attribute and the reset moment in `last_reset`.

Example schedule with default 15-minute interval and 10-second processing delay:

- `hh:00:10`
- `hh:15:10`
- `hh:30:10`
- `hh:45:10`

The integration waits briefly for both source meters to update and synchronize, then processes exactly one interval.

## Required existing source entities

You need three kinds of existing Home Assistant entities before setup:

| Purpose | Example entity ID | Required attributes |
|--------|-------------------|-------------------|
| Receiving grid import (15 min) | `sensor.hodnik_elektro_stevec_prevzem_iz_omrezja_15min` | `last_period`, `last_reset`, energy unit |
| Allocated shared energy (15 min) | `sensor.trata_solaredge_gn_souporaba_15min` | `last_period`, `last_reset`, energy unit |
| Allocation percentage | `input_number.trenutni_odstotek_souporabe` | numeric state |

These exact IDs are **examples only**. You select your real entities in the config flow.

### Verify `last_period` and `last_reset`

1. Open **Developer Tools → States**
2. Search for your Utility Meter entity
3. Confirm attributes include:
   - `last_period` — numeric, non-negative
   - `last_reset` — ISO timestamp of the latest reset
   - `unit_of_measurement` — `kWh` or `Wh`

Example:

```yaml
state: 0.12
attributes:
  last_period: 0.84
  last_reset: '2026-07-12T14:15:00+02:00'
  unit_of_measurement: kWh
```

## Created sensors

### Last completed interval sensors

| Sensor | Meaning |
|--------|---------|
| Imported energy (last interval) | Receiving household grid import for the last processed interval |
| Allocated shared energy (last interval) | Energy allocated to the receiver for that interval |
| Inferred provider export (last interval) | `shared × 100 / allocation %` |
| Used shared energy (last interval) | `min(shared, imported)` |
| Unused shared energy (last interval) | Shared energy not consumed locally |
| Billable grid energy (last interval) | Grid import still billable after shared allocation |
| Required allocation percentage (last interval) | Percentage needed to cover import; may exceed 100% |
| Ideal allocation percentage (last interval) | Required percentage clamped to 0–100% |
| Allocation utilization (last interval) | Share of allocated energy actually used |
| Consumption coverage (last interval) | Share of import covered by allocated energy |

### Cumulative energy sensors

These use `device_class: energy` and `state_class: total_increasing`:

- Total imported energy
- Total allocated shared energy
- Total used shared energy
- Total unused shared energy
- Total billable grid energy

They are suitable as sources for daily/monthly/yearly Utility Meter helpers and long-term statistics. They only decrease when you explicitly run the **Reset totals** action.

### Status / diagnostic sensors

- Last processed interval timestamp
- Processed interval count
- Skipped interval count
- Integration status
- Current allocation percentage

## Installation

### Option A: HACS custom repository

1. Open **HACS → Integrations**
2. Click the three-dot menu → **Custom repositories**
3. Add this repository URL and category **Integration**
4. Click **Download**
5. **Restart Home Assistant**

### Option B: Manual installation

1. Copy the folder `custom_components/energy_sharing` into your Home Assistant `config/custom_components/` directory
2. The result should be:

```text
config/
  custom_components/
    energy_sharing/
      __init__.py
      manifest.json
      ...
```

3. **Restart Home Assistant**

## Configuration

1. Go to **Settings → Devices & services**
2. Click **Add integration**
3. Search for **Energy Sharing**
4. Complete the setup form:
   - Select the grid-import Utility Meter
   - Select the shared-energy Utility Meter
   - Choose percentage source:
     - **Read from entity** — e.g. your `input_number`
     - **Use fixed percentage** — stored in integration options
5. Finish the flow

### Change settings later

Open the config entry → **Configure** to change:

- integration name
- interval length
- processing delay
- retry / synchronization settings
- fixed percentage (if using fixed mode)

Source entity selections are identity settings and require removing/re-adding the integration to change.

## Diagnostics

1. Open **Settings → Devices & services → Energy Sharing**
2. Select your config entry
3. Click **Download diagnostics**

Diagnostics include sanitized config, source entity snapshots, counters, scheduler/retry state, and the latest interval result.

## Lovelace examples

### Last interval overview

```yaml
type: entities
title: Energy Sharing – last interval
entities:
  - entity: sensor.energy_sharing_imported_energy_last_interval
  - entity: sensor.energy_sharing_allocated_shared_energy_last_interval
  - entity: sensor.energy_sharing_used_shared_energy_last_interval
  - entity: sensor.energy_sharing_unused_shared_energy_last_interval
  - entity: sensor.energy_sharing_billable_grid_energy_last_interval
  - entity: sensor.energy_sharing_integration_status
```

Entity IDs depend on your device/entity naming. Use **Developer Tools → States** to find the exact IDs created on your system.

### Statistics graph for allocation percentages

```yaml
type: statistics-graph
title: Allocation percentages
chart_type: line
days_to_show: 7
entities:
  - entity: sensor.energy_sharing_required_allocation_percentage_last_interval
  - entity: sensor.energy_sharing_ideal_allocation_percentage_last_interval
```

### History graph for interval energy split

```yaml
type: history-graph
title: Interval energy split
hours_to_show: 48
entities:
  - entity: sensor.energy_sharing_used_shared_energy_last_interval
  - entity: sensor.energy_sharing_unused_shared_energy_last_interval
  - entity: sensor.energy_sharing_billable_grid_energy_last_interval
```

### Cumulative totals

```yaml
type: entities
title: Cumulative settlement totals
entities:
  - entity: sensor.energy_sharing_total_imported_energy
  - entity: sensor.energy_sharing_total_allocated_shared_energy
  - entity: sensor.energy_sharing_total_used_shared_energy
  - entity: sensor.energy_sharing_total_unused_shared_energy
  - entity: sensor.energy_sharing_total_billable_grid_energy
```

### Using cumulative sensors with Utility Meter helpers

Create a Utility Meter with a cumulative sensor as source, for example:

```yaml
utility_meter:
  daily_shared_used:
    source: sensor.energy_sharing_total_used_shared_energy
    cycle: daily
```

## Testing with `energy_sharing.process_now`

Use this action to manually attempt processing of the latest completed interval.

**Developer Tools → Actions**

```yaml
action: energy_sharing.process_now
target:
  device_id:
    - <your_energy_sharing_device_id>
```

Or via the UI: select the Energy Sharing device as the action target.

Behavior:

- respects duplicate protection
- does not double-count an already processed interval
- logs a clear result (`processed`, `duplicate`, `skipped:...`, `retrying:...`)

### Reset totals

```yaml
action: energy_sharing.reset_totals
target:
  device_id:
    - <your_energy_sharing_device_id>
data:
  confirm: true
```

This resets cumulative totals and counters only. Source Utility Meters are untouched.

## Troubleshooting

| Symptom | Likely cause | What to do |
|--------|--------------|------------|
| Setup fails on Utility Meter | `last_period` missing or invalid | Verify Utility Meter helper configuration and attributes |
| Wrong values | incorrect entity selected | Re-check entity IDs in diagnostics |
| Status `inputs_unsynchronized` | `last_reset` timestamps differ too much | Increase reset tolerance in options or inspect meter reset timing |
| Status `percentage_invalid` | percentage entity unavailable or zero | Ensure percentage entity is available and > 0 |
| Setup error `invalid_utility_meter` | unsupported unit | Use `kWh` or `Wh` source entities |
| `duplicate` result from `process_now` | interval already processed | Expected behavior; wait for next interval |
| Missing historical intervals after outage | only latest completed interval can be identified | See warning below |

## Missed intervals warning

If Home Assistant is offline across multiple 15-minute boundaries, the integration **cannot reconstruct** missed historical intervals from a single `last_period` value. When service resumes, it processes only the latest clearly identifiable completed interval and records missed intervals in counters/diagnostics.

## Removal

1. Go to **Settings → Devices & services → Energy Sharing**
2. Open the config entry menu → **Delete**
3. Optionally remove `custom_components/energy_sharing` from your config directory
4. Restart Home Assistant

## Development

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run tests

```bash
pytest -q
```

### Lint / type check

```bash
ruff check custom_components tests
mypy custom_components
```

## License

MIT — see [LICENSE](LICENSE).
