# Energy Sharing

Home Assistant custom integration that calculates **solar energy sharing settlement** between two households.

The energy provider exports surplus solar energy to the grid. A configurable percentage of that exported energy is contractually allocated to the receiving household. This integration performs settlement **independently for every completed 15-minute interval** on the **receiving** Home Assistant instance.

> **Important:** Shared energy is an **accounting allocation through the grid**, not locally generated solar energy at the receiving household. Interval energy sensors describe settlement results, not physical on-site production.

## What this integration does

For each completed 15-minute interval, the integration reads:

1. **Provider export** — full grid export from the provider household (direct input)
2. **Receiver grid import** — grid import at the receiving household
3. **Allocation percentage** — from an entity or a fixed configured value
4. **Reported allocated energy** *(optional)* — for reconciliation only

It then calculates:

- calculated allocated energy (`provider_export × percentage / 100`)
- used / unused shared energy
- billable grid energy
- required and ideal allocation percentages
- utilization and coverage percentages
- optional reconciliation against reported allocation
- cumulative totals suitable for long-term statistics and Utility Meter helpers

Processing happens **once per completed interval**, shortly after each quarter-hour boundary. It does not recalculate on every source entity change.

## Input entities

See the dedicated guide: [docs/INPUT_ENTITIES.md](docs/INPUT_ENTITIES.md)

| Input | Required | Example |
| Provider export, last interval | Yes | `sensor.trata_solaredge_oddaja_v_omrezje_15min` |
| Receiver import, last interval | Yes | `sensor.hodnik_elektro_stevec_prevzem_iz_omrezja_15min` |
| Allocation percentage | Yes | `input_number.trenutni_odstotek_souporabe` or fixed value |
| Reported allocated energy | No | `sensor.trata_solaredge_gn_souporaba_15min` |

### Provider export interval source (required)

Represents the provider household's **full energy export to the grid** for the last completed interval, **before** any allocation percentage is applied. This value is used directly — the integration does **not** reconstruct export by dividing allocated energy by 7% or any other percentage.

### Receiver grid import interval source (required)

Represents the receiving household's grid import for the same last completed interval.

### Allocation percentage (required)

Choose **entity mode** (for example `input_number.trenutni_odstotek_souporabe`) or **fixed mode** (stored in options). The effective percentage is persisted with each processed interval.

### Optional reported allocated energy source

When configured, this source is compared against the calculated allocation for diagnostics. Reconciliation passes when **either** the absolute difference in kWh **or** the percentage difference is within configured tolerances.

### Required attributes

All interval sources must expose `last_period`, `last_reset`, and `unit_of_measurement` (`kWh` or `Wh`).

Inspect them under **Developer Tools → States**:

```yaml
state: 0.12
attributes:
  last_period: 0.123
  last_reset: 2026-07-12T14:15:00+02:00
  unit_of_measurement: kWh
```

Entities may be MQTT-mirrored from a remote Home Assistant instance; MQTT transport is outside this integration's scope.

## 15-minute settlement model

Utility Meter helpers reset at interval boundaries (`:00`, `:15`, `:30`, `:45`). After a boundary, they expose the completed interval value in `last_period` and the reset moment in `last_reset`.

The integration normalizes `last_reset` to timezone-aware UTC before comparison and uses that boundary as the stable interval ID.

Example schedule with default 15-minute interval and 10-second processing delay:

- `hh:00:10`
- `hh:15:10`
- `hh:30:10`
- `hh:45:10`

## Created sensors

### Last completed interval — energy

- Provider export
- Receiver grid import
- Calculated allocated energy
- Reported allocated energy *(when configured)*
- Allocation difference *(when configured)*
- Used shared energy
- Unused shared energy
- Billable grid energy

### Last completed interval — percentages

- Effective allocation percentage
- Allocation difference percentage *(when configured)*
- Required allocation percentage
- Ideal allocation percentage
- Allocation utilization
- Consumption coverage

### Status / diagnostic sensors

- Interval start / interval end
- Last processed interval
- Reconciliation status
- Processing status
- Last skip/failure reason
- Successful interval count
- Skipped interval count
- Reconciliation mismatch count
- Current allocation percentage

### Cumulative energy sensors

`device_class: energy`, `state_class: total_increasing`:

- Total provider export processed
- Total receiver grid import
- Total calculated allocated energy
- Total used shared energy
- Total unused shared energy
- Total billable grid energy

## Installation

### Option A: HACS custom repository

1. Open **HACS → Integrations**
2. Click the three-dot menu → **Custom repositories**
3. Add this repository URL and category **Integration**
4. Click **Download**
5. **Restart Home Assistant**

### Option B: Manual installation

Copy `custom_components/energy_sharing` into `config/custom_components/` and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services**
2. Click **Add integration**
3. Search for **Energy Sharing**
4. Complete the setup form:
   - Provider export interval source
   - Receiver grid import interval source
   - Allocation percentage mode (entity or fixed)
   - Optional reported allocated energy source
5. Finish the flow

### Change settings later

Open the config entry → **Configure** to change:

- allocation percentage mode, entity, or fixed value
- optional reported allocation source
- interval length, processing delay, retry settings
- reset timestamp tolerance
- allocation reconciliation tolerances and failure mode

Provider export and receiver import are identity settings and require removing/re-adding the integration to change.

## Diagnostics

Download diagnostics from the config entry. Diagnostics include sanitized config, source snapshots, reconciliation details, counters, scheduler/retry state, and the latest interval result.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check custom_components tests
mypy custom_components
```

## Migration from v1

Config entry version 1 entries are migrated automatically:

- `grid_import_entity` → `receiver_import_source`
- `shared_energy_entity` → optional `reported_allocation_source`
- percentage settings move to options

**You must add a provider export interval source** after migration. Cumulative totals are preserved where possible, but `last_interval` and duplicate protection are cleared because v1 calculations used a different input model.

## License

MIT — see [LICENSE](LICENSE).
