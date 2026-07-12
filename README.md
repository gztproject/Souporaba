<p align="center">
  <img src="graphics/banner.png" alt="Energy Sharing" width="640">
</p>

# Energy Sharing

Home Assistant custom integration that calculates **solar energy sharing settlement** between an **Oddajnik (Provider)** and a **Prejemnik (Receiver)** using **cumulative energy counters** and an **internal 15-minute interval engine**.

The integration runs on the **Prejemnik (Receiver)** Home Assistant instance. It does **not** require Utility Meter helpers or `last_period` / `last_reset` attributes.

## What this integration does

1. Reads cumulative energy totals for receiver grid import and allocated shared energy.
2. Optionally reads cumulative provider grid export and/or a fixed contractual allocation percentage.
3. Creates aligned 15-minute intervals internally.
4. Calculates interval deltas from persisted boundary snapshots.
5. Computes settlement values, optional reconciliation, and integration-owned cumulative totals.

## Input entities

See [docs/INPUT_ENTITIES.md](docs/INPUT_ENTITIES.md).

| Input | Required | Meaning |
| Prejemnik (Receiver) total grid import | Yes | Cumulative energy imported by the receiver (`receiver_import_total_source`) |
| Total received shared energy | Yes | Cumulative energy allocated to the receiver (`shared_energy_total_source`) |
| Fixed allocation percentage | Conditional | Required when Oddajnik (Provider) export is not supplied |
| Oddajnik (Provider) total grid export | Conditional | Full cumulative exported surplus (`provider_export_total_source`) |

At least one of **fixed allocation percentage** or **provider total grid export** is required.

### Operating modes

- **Percentage-only** — infers provider export from shared energy and fixed percentage
- **Export-only** — uses measured provider export; effective percentage is derived
- **Export + percentage (preferred)** — measured export with reconciliation against shared energy

## First setup behavior

The first completed boundary after setup establishes a **baseline snapshot only**. No settlement energy is accumulated for the partial interval before that baseline.

## Installation

Copy `custom_components/energy_sharing` into `config/custom_components/` and restart Home Assistant, or install via HACS.

Brand images live in `custom_components/energy_sharing/brand/` (`icon.png`, `logo.png`, and `@2x` variants). Home Assistant **2026.3+** serves them automatically. On older Home Assistant versions, the integrations UI may still show a generic placeholder until you upgrade.

## Configuration

1. **Settings → Devices & services → Add integration**
2. Search for **Energy Sharing**
3. Select:
   - Prejemnik (Receiver) total grid import cumulative sensor (e.g. `sensor.receiver_grid_import_total`)
   - Total received shared energy cumulative sensor (e.g. `sensor.receiver_shared_energy_total`)
   - Fixed allocation percentage and/or Oddajnik (Provider) total grid export (e.g. `sensor.provider_grid_export_total`)

## Services

- `energy_sharing.process_now` — process the latest eligible boundary
- `energy_sharing.reset_totals` — reset integration-owned cumulative totals (requires `confirm: true`)
- `energy_sharing.reinitialize_baseline` — record current source totals as a fresh baseline

## Migration from earlier versions

Versions that used 15-minute Utility Meter interval sources (`last_period` / `last_reset`) are **not compatible** with the cumulative-counter model. Config entries are migrated structurally, but you must verify and update source entities. Storage baselines and last-interval results are cleared; integration-owned cumulative totals are preserved where safe. Run **Reinitialize baseline** after reconfiguration.

## Development

### Branching

| Branch | Purpose |
| `master` | Stable releases only; each release is tagged (`vX.Y.Z`) |
| `dev` | Integration branch for ongoing work |
| `feature/*` | New features — branch from `dev`, merge back to `dev` |
| `bugfix/*` | Bug fixes — branch from `dev`, merge back to `dev` |
| `hotfix/*` | Urgent production fixes — branch from `master`, merge to `master` and `dev` |

**Day-to-day workflow**

1. Branch from `dev`: `git checkout dev && git pull && git checkout -b feature/my-change`
2. Open a PR into `dev` when ready.
3. For a release: merge `dev` → `master`, bump `custom_components/energy_sharing/manifest.json` version, tag, and create a GitHub Release.
4. Merge `master` back into `dev` so both branches stay aligned.

**Versioning (HACS)**

HACS reads the version from `manifest.json`. Bump that field for every release, then tag the commit (e.g. `v0.1.1`) and publish a GitHub Release.

### Local setup

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
