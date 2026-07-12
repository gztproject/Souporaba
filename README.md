# Energy Sharing

Home Assistant custom integration that calculates **solar energy sharing settlement** between two households using **cumulative energy counters** and an **internal 15-minute interval engine**.

The integration runs on the **receiving** household Home Assistant instance. It does **not** require Utility Meter helpers or `last_period` / `last_reset` attributes.

## What this integration does

1. Reads cumulative energy totals for receiver grid import and allocated shared energy.
2. Optionally reads cumulative provider grid export and/or a fixed contractual allocation percentage.
3. Creates aligned 15-minute intervals internally.
4. Calculates interval deltas from persisted boundary snapshots.
5. Computes settlement values, optional reconciliation, and integration-owned cumulative totals.

## Input entities

See [docs/INPUT_ENTITIES.md](docs/INPUT_ENTITIES.md).

| Input | Required | Meaning |
| Receiver total grid import | Yes | Cumulative energy imported by the receiving household |
| Total received shared energy | Yes | Cumulative energy allocated to the receiver (`shared_energy_total_source`) |
| Fixed allocation percentage | Conditional | Required when provider export is not supplied |
| Provider total grid export | Conditional | Full cumulative exported surplus (`provider_export_total_source`) |

At least one of **fixed allocation percentage** or **provider total grid export** is required.

### Operating modes

- **Percentage-only** — infers provider export from shared energy and fixed percentage
- **Export-only** — uses measured provider export; effective percentage is derived
- **Export + percentage (preferred)** — measured export with reconciliation against shared energy

## First setup behavior

The first completed boundary after setup establishes a **baseline snapshot only**. No settlement energy is accumulated for the partial interval before that baseline.

## Installation

Copy `custom_components/energy_sharing` into `config/custom_components/` and restart Home Assistant, or install via HACS.

## Configuration

1. **Settings → Devices & services → Add integration**
2. Search for **Energy Sharing**
3. Select:
   - Receiver total grid import cumulative sensor
   - Total received shared energy cumulative sensor
   - Fixed allocation percentage and/or provider total grid export

## Services

- `energy_sharing.process_now` — process the latest eligible boundary
- `energy_sharing.reset_totals` — reset integration-owned cumulative totals (requires `confirm: true`)
- `energy_sharing.reinitialize_baseline` — record current source totals as a fresh baseline

## Migration from earlier versions

Versions that used 15-minute Utility Meter interval sources (`last_period` / `last_reset`) are **not compatible** with the cumulative-counter model. Config entries are migrated structurally, but you must verify and update source entities. Storage baselines and last-interval results are cleared; integration-owned cumulative totals are preserved where safe. Run **Reinitialize baseline** after reconfiguration.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check custom_components tests
mypy custom_components
```

## License

MIT — see [LICENSE](LICENSE).
