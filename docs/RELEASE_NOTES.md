## Energy Sharing v0.3.0-rc.3 (release candidate)

Fixes found in the rc.2 two-month soak, plus the analysis export pack and a config-number for the monthly allocation percentage.

A brief `0` flash on a mirrored shared-energy counter was treated as a real meter reset; the restored total was then accumulated as energy (~411.6 kWh of fake shared / unused on the Trata soak). Upgrade, then **reset integration totals** so those cumulatives start clean.

### Fixes since rc.2

- Retry apparent counter drops for `max_wait` instead of committing a reset on a 0-flash.
- If a reset was already committed and the old total comes back, skip that jump (do not accumulate it).
- Skip physically impossible interval jumps (above 100 kW continuous).
- Count missed intervals once (no extra +1 on the failure record).
- Fix Energy Sharing actions on Home Assistant 2026.10 (`ServiceCall` has no `.target`). **Reset totals** and the other device actions no longer fail with Unknown error.

### Also in this RC

- Persist a rolling 14-month 15-minute archive and export a period-selectable CSV pack (`energy_sharing.export_analysis_pack`) under **Media → Local → energy_sharing**.
- Conservative / optimistic next-month share recommendations from archived intervals.
- Config number: **Fixed allocation percentage** (monthly Moj Elektro % without opening Options).

### After upgrade: reset totals

Required if you ran **rc.2** (or earlier) through the soak. The engine is already on the correct live snapshot; only the **integration-owned cumulatives** are poisoned (used / unused / shared / expected / import / export / billable, processed/skipped counters, ideal-share history, and ALC mopped/overshoot/undershoot).

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

### Soak checklist

- Reset totals after the first restart (steps above).
- Confirm cumulative shared ≈ cumulative expected at 7% (they should track again).
- Watch logs around remote/MQTT reconnects: a 0-flash should `retrying:counter_reset` and recover, not add hundreds of kWh.
- Confirm ALC still turns owned boilers off at interval end after a switch reconnect or attribute update.

### Install

Use this release for HACS/manual updates while soaking toward stable **0.3.0**.
