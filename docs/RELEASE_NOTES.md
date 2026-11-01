## Energy Sharing v0.3.0

Stable release after the 0.3.0 beta/RC soak. Cumulative-counter settlement, multi-load active-load control, the 15-minute analysis archive, and monthly allocation controls.

Set **Fixed allocation percentage** to **0** to pause sharing for a month (expected shared energy is 0; active-load control stops soaking surplus). Set it back above 0 when sharing starts again. Register the same 0% in Moj Elektro — this integration only monitors and controls locally.

### Since rc.3

- Allow a **0%** contractual allocation to pause a month without removing the percentage or the integration.

### Highlights

- Settlement from cumulative energy counters (no Utility Meter `last_period` / `last_reset`).
- Multi-load active-load control: ownership through unavailable flickers, owned vs all-load energy, min-start, linear leftover prediction, dark-interval skip.
- Rolling 14-month 15-minute archive and `energy_sharing.export_analysis_pack` under **Media → Local → energy_sharing**.
- Conservative / optimistic next-month share recommendations.
- Config number: **Fixed allocation percentage** (0–100, including 0 to pause).
- Home Assistant 2026.10 device actions (`ServiceCall` has no `.target`).

### Fixes carried from rc.2 / rc.3

- Retry apparent counter drops for `max_wait` instead of committing a reset on a 0-flash.
- If a reset was already committed and the old total comes back, skip that jump (do not accumulate it).
- Skip physically impossible interval jumps (above 100 kW continuous).
- Count missed intervals once (no extra +1 on the failure record).

A brief `0` flash on a mirrored shared-energy counter was treated as a real meter reset in rc.2; the restored total was then accumulated as energy (~411.6 kWh of fake shared / unused on the Trata soak). If you ran **rc.2 or earlier** through that soak and have not already reset, **reset integration totals** so those cumulatives start clean. Not required if you already reset on rc.3.

### After upgrade from rc.2 or earlier: reset totals

Required if you ran **rc.2** (or earlier) through the soak and did not reset on rc.3. The engine is already on the correct live snapshot; only the **integration-owned cumulatives** are poisoned (used / unused / shared / expected / import / export / billable, processed/skipped counters, ideal-share history, and ALC mopped/overshoot/undershoot).

This does **not** change Oddajnik/Prejemnik source meters. It does **not** reinitialize the baseline.

#### UI

1. Update to this release and **restart Home Assistant**.
2. Go to **Developer tools → Actions**.
3. Choose **Energy Sharing: Reset totals**.
4. Under **Targets**, select the Energy Sharing device (for example *Souporaba Trata*). Skip this if you have only one Energy Sharing instance.
5. Turn on **Confirm reset**.
6. **Perform action**.

You should see integration cumulative sensors return to `0`. The next completed 15-minute boundary will start accumulating again. Leave **Reinitialize baseline** alone unless you also want to drop the current partial interval.

#### YAML

```yaml
action: energy_sharing.reset_totals
data:
  confirm: true
target:
  device_id: YOUR_ENERGY_SHARING_DEVICE_ID
```

`confirm: true` is required. If the action fails with `confirmation_required`, the toggle/field was left off.

### Install

HACS or manual update, then **restart Home Assistant**. Track tagged releases on [GitHub Releases](https://github.com/gztproject/Souporaba/releases).
