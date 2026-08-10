"""Tests for active load runtime helpers."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.energy_sharing.active_loads import (
    ActiveLoadConfig,
    ActiveLoadController,
    parse_power_watts,
)
from custom_components.energy_sharing.const import (
    CONF_ACTIVE_LOAD_CONTROL_ENABLED,
    CONF_ACTIVE_LOAD_MIN_ON_SECONDS,
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
)


class _FakeManager:
    def __init__(self, options: dict) -> None:
        self._options = options
        self.notify_calls = 0
        self._stored_estimates: dict[str, float] = {}
        self._stored_cumulative: dict[str, float] = {
            "mopped_up_wh": 0.0,
            "overshoot_wh": 0.0,
            "undershoot_wh": 0.0,
        }

    def get_option(self, key: str, default=None):
        return self._options.get(key, default)

    def notify_entities_update(self) -> None:
        self.notify_calls += 1

    def get_active_load_estimated_power_map(self) -> dict[str, float]:
        return dict(self._stored_estimates)

    async def async_persist_active_load_estimated_power(
        self, switch_entity_id: str, power_w: float
    ) -> None:
        self._stored_estimates[switch_entity_id] = power_w

    def get_active_load_cumulative_stats(self) -> dict[str, float]:
        return dict(self._stored_cumulative)

    def update_active_load_cumulative_stats(
        self,
        *,
        mopped_up_wh: float,
        overshoot_wh: float,
        undershoot_wh: float,
    ) -> None:
        self._stored_cumulative = {
            "mopped_up_wh": mopped_up_wh,
            "overshoot_wh": overshoot_wh,
            "undershoot_wh": undershoot_wh,
        }


def test_parse_power_watts_w_and_kw() -> None:
    assert parse_power_watts("100", "W") == 100.0
    assert parse_power_watts("1.5", "kW") == 1500.0
    assert parse_power_watts("bad", "W") is None


def test_predict_budget_equals_unused_when_alc_did_not_run() -> None:
    unused_wh, predicted_wh = ActiveLoadController._predict_unused_budget_wh(
        unused_shared_kwh=0.08,
        shared_energy_kwh=0.10,
        expected_shared_kwh=0.10,
        receiver_import_kwh=0.02,
        active_load_kwh=0.0,
    )
    assert unused_wh == pytest.approx(80.0)
    assert predicted_wh == pytest.approx(80.0)


def test_predict_budget_keeps_firing_after_successful_soak() -> None:
    # Prior slot: ALC soaked leftover so measured unused is ~0, but house baseline
    # alone would still leave most of the share unused next slot.
    unused_wh, predicted_wh = ActiveLoadController._predict_unused_budget_wh(
        unused_shared_kwh=0.0,
        shared_energy_kwh=0.10,
        expected_shared_kwh=0.10,
        receiver_import_kwh=0.10,
        active_load_kwh=0.09,
    )
    assert unused_wh == pytest.approx(0.0)
    assert predicted_wh == pytest.approx(90.0)


def test_predict_budget_uses_expected_shared_when_present() -> None:
    _unused_wh, predicted_wh = ActiveLoadController._predict_unused_budget_wh(
        unused_shared_kwh=0.0,
        shared_energy_kwh=0.12,
        expected_shared_kwh=0.10,
        receiver_import_kwh=0.10,
        active_load_kwh=0.09,
    )
    assert predicted_wh == pytest.approx(90.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_notify_uses_predicted_budget_every_slot(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        hass.states.async_set("switch.boiler_a", "off")
        hass.states.async_set(
            "sensor.boiler_a_power",
            "2000",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )
        await hass.async_block_till_done()

        # Successful soak last interval: unused=0 but ALC consumed 90 Wh.
        # Single lit sample → fall back to last-interval leftover.
        controller.notify_processed_interval(
            unused_shared_kwh=0.0,
            shared_energy_kwh=0.10,
            expected_shared_kwh=0.10,
            receiver_import_kwh=0.10,
            active_load_kwh=0.09,
        )
        snapshot = controller.get_snapshot()
        assert snapshot["last_unused_shared_wh"] == pytest.approx(0.0)
        assert snapshot["last_interval_base_target_wh"] == pytest.approx(90.0)
        assert snapshot["target_wh"] == pytest.approx(90.0)
        assert snapshot["prediction_sample_count"] == 1
    finally:
        await controller.async_unload()


async def _setup_predict_controller(hass: HomeAssistant) -> ActiveLoadController:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    hass.states.async_set("switch.boiler_a", "off")
    hass.states.async_set(
        "sensor.boiler_a_power",
        "2000",
        attributes={"unit_of_measurement": "W", "device_class": "power"},
    )
    await hass.async_block_till_done()
    return controller


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_linear_prediction_rising_shared_above_last_interval(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        # Rising potential, flat organic baseline → next leftover above last sample.
        samples = [
            (0.10, 0.02),
            (0.15, 0.02),
            (0.20, 0.02),
        ]
        for potential, import_kwh in samples:
            controller.notify_processed_interval(
                unused_shared_kwh=max(potential - import_kwh, 0.0),
                shared_energy_kwh=potential,
                expected_shared_kwh=potential,
                receiver_import_kwh=import_kwh,
                active_load_kwh=0.0,
            )
        snapshot = controller.get_snapshot()
        last_interval_leftover_wh = (0.20 - 0.02) * 1000.0
        assert snapshot["prediction_sample_count"] == 3
        assert snapshot["last_interval_base_target_wh"] > last_interval_leftover_wh
        assert snapshot["predicted_potential_kwh"] is not None
        assert snapshot["predicted_potential_kwh"] > 0.20
        assert snapshot["predicted_baseline_kwh"] == pytest.approx(0.02)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_linear_prediction_falling_shared_below_last_interval(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        samples = [
            (0.30, 0.05),
            (0.22, 0.08),
            (0.14, 0.11),
        ]
        for potential, import_kwh in samples:
            controller.notify_processed_interval(
                unused_shared_kwh=max(potential - import_kwh, 0.0),
                shared_energy_kwh=potential,
                expected_shared_kwh=potential,
                receiver_import_kwh=import_kwh,
                active_load_kwh=0.0,
            )
        snapshot = controller.get_snapshot()
        last_interval_leftover_wh = (0.14 - 0.11) * 1000.0
        assert snapshot["prediction_sample_count"] == 3
        assert snapshot["last_interval_base_target_wh"] < last_interval_leftover_wh
        assert snapshot["predicted_potential_kwh"] is not None
        assert snapshot["predicted_potential_kwh"] < 0.14
        assert snapshot["predicted_baseline_kwh"] is not None
        assert snapshot["predicted_baseline_kwh"] > 0.11
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_linear_prediction_skips_dark_zero_potential(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        controller.notify_processed_interval(
            unused_shared_kwh=0.0,
            shared_energy_kwh=0.0,
            expected_shared_kwh=0.0,
            receiver_import_kwh=0.05,
            active_load_kwh=0.0,
        )
        snapshot = controller.get_snapshot()
        assert snapshot["prediction_sample_count"] == 0
        assert snapshot["last_interval_base_target_wh"] == pytest.approx(0.0)

        controller.notify_processed_interval(
            unused_shared_kwh=0.08,
            shared_energy_kwh=0.10,
            expected_shared_kwh=0.10,
            receiver_import_kwh=0.02,
            active_load_kwh=0.0,
        )
        snapshot = controller.get_snapshot()
        assert snapshot["prediction_sample_count"] == 1
        # Still single lit sample → last-interval fallback.
        assert snapshot["last_interval_base_target_wh"] == pytest.approx(80.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_correction_deadband_skips_tiny_tracking_error(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        # Roll copies interval_target/owned_measured into previous_* for correction.
        controller._interval.interval_id = "old-interval"  # noqa: SLF001
        controller._interval.interval_target_wh = 100.0  # noqa: SLF001
        controller._interval.measured_total_wh = 98.5  # noqa: SLF001
        controller._interval.owned_measured_total_wh = 98.5  # noqa: SLF001
        controller.notify_processed_interval(
            unused_shared_kwh=0.08,
            shared_energy_kwh=0.10,
            expected_shared_kwh=0.10,
            receiver_import_kwh=0.02,
            active_load_kwh=0.0,
        )
        snapshot = controller.get_snapshot()
        # |error|=1.5 Wh < default deadband 3 Wh → no correction.
        assert snapshot["applied_correction_wh"] == pytest.approx(0.0)
        assert snapshot["tracking_error_wh"] == pytest.approx(1.5)
        assert snapshot["target_wh"] == pytest.approx(80.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_non_owned_energy_does_not_count_as_overshoot(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        load = controller._loads[0]  # noqa: SLF001
        load.owns_switch = False
        load.switch_is_on = True
        load.measured_power_w = 2000.0
        controller._interval.interval_id = "old-interval"  # noqa: SLF001
        controller._interval.interval_target_wh = 50.0  # noqa: SLF001
        controller._interval.measured_total_wh = 400.0  # noqa: SLF001
        controller._interval.owned_measured_total_wh = 0.0  # noqa: SLF001
        controller.notify_processed_interval(
            unused_shared_kwh=0.0,
            shared_energy_kwh=0.05,
            expected_shared_kwh=0.05,
            receiver_import_kwh=0.40,
            active_load_kwh=0.0,
        )
        snapshot = controller.get_snapshot()
        assert snapshot["tracking_error_wh"] == pytest.approx(0.0)
        assert snapshot["applied_correction_wh"] == pytest.approx(0.0)
        assert snapshot["cumulative_overshoot_wh"] == pytest.approx(0.0)
        assert snapshot["cumulative_undershoot_wh"] == pytest.approx(0.0)
        assert snapshot["cumulative_mopped_up_wh"] == pytest.approx(0.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_skips_start_when_allocation_below_min_on_energy(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager(
        {
            CONF_ACTIVE_LOAD_MIN_ON_SECONDS: 25,
        }
    )
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        hass.states.async_set("switch.boiler_a", "off")
        hass.states.async_set(
            "sensor.boiler_a_power",
            "1800",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )
        await hass.async_block_till_done()
        load = controller._loads[0]  # noqa: SLF001
        load.estimated_power_w = 1800.0
        load.measured_power_w = 1800.0
        load.switch_is_on = False
        load.switch_available = True
        controller._interval.interval_id = "interval-1"  # noqa: SLF001
        controller._interval.interval_end = dt_util.now() + timedelta(minutes=10)  # noqa: SLF001
        controller._interval.interval_target_wh = 8.0  # noqa: SLF001
        # 1800W * 25s = 12.5 Wh min-on; 8 Wh leftover must not start.
        controller._allocate_targets(8.0)  # noqa: SLF001
        assert load.allocated_target_wh == pytest.approx(0.0)
        assert load.skip_reason == "below_min_start"
        await controller._apply_control()  # noqa: SLF001
        assert load.owns_switch is False
        assert load.skip_reason == "below_min_start"
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_mixed_owned_and_external_tracks_overshoot_not_undershoot(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        controller._interval.interval_id = "old-interval"  # noqa: SLF001
        controller._interval.interval_target_wh = 50.0  # noqa: SLF001
        controller._interval.owned_measured_total_wh = 30.0  # noqa: SLF001
        controller._interval.measured_total_wh = 60.0  # noqa: SLF001
        controller.notify_processed_interval(
            unused_shared_kwh=0.0,
            shared_energy_kwh=0.05,
            expected_shared_kwh=0.05,
            receiver_import_kwh=0.06,
            active_load_kwh=0.03,
        )
        snapshot = controller.get_snapshot()
        assert snapshot["tracking_error_wh"] == pytest.approx(-10.0)
        assert snapshot["applied_correction_wh"] == pytest.approx(-5.0)
        assert snapshot["cumulative_overshoot_wh"] == pytest.approx(10.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_below_min_start_interval_applies_no_correction(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager({CONF_ACTIVE_LOAD_MIN_ON_SECONDS: 25})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        load = controller._loads[0]  # noqa: SLF001
        load.estimated_power_w = 1800.0
        for measured_wh in (0.0, 0.5, 2.0):
            controller._interval.interval_id = "old-interval"  # noqa: SLF001
            controller._interval.interval_target_wh = 8.0  # noqa: SLF001
            controller._interval.owned_measured_total_wh = 0.0  # noqa: SLF001
            controller._interval.measured_total_wh = measured_wh  # noqa: SLF001
            controller.notify_processed_interval(
                unused_shared_kwh=0.0,
                shared_energy_kwh=0.01,
                expected_shared_kwh=0.01,
                receiver_import_kwh=0.01,
                active_load_kwh=0.0,
            )
            snapshot = controller.get_snapshot()
            assert snapshot["tracking_error_wh"] == pytest.approx(0.0)
            assert snapshot["applied_correction_wh"] == pytest.approx(0.0)
            assert snapshot["cumulative_undershoot_wh"] == pytest.approx(0.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_partial_external_below_min_start_applies_no_correction(
    hass: HomeAssistant,
) -> None:
    controller = await _setup_predict_controller(hass)
    try:
        controller._loads[0].estimated_power_w = 1800.0  # noqa: SLF001
        controller._interval.interval_id = "old-interval"  # noqa: SLF001
        controller._interval.interval_target_wh = 50.0  # noqa: SLF001
        controller._interval.owned_measured_total_wh = 0.0  # noqa: SLF001
        controller._interval.measured_total_wh = 40.0  # noqa: SLF001
        controller.notify_processed_interval(
            unused_shared_kwh=0.0,
            shared_energy_kwh=0.05,
            expected_shared_kwh=0.05,
            receiver_import_kwh=0.05,
            active_load_kwh=0.0,
        )
        snapshot = controller.get_snapshot()
        assert snapshot["tracking_error_wh"] == pytest.approx(0.0)
        assert snapshot["applied_correction_wh"] == pytest.approx(0.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_prediction_uses_owned_active_load_only(
    hass: HomeAssistant,
) -> None:
    _unused_wh, owned_predicted = ActiveLoadController._predict_unused_budget_wh(
        unused_shared_kwh=0.0,
        shared_energy_kwh=0.15,
        expected_shared_kwh=0.15,
        receiver_import_kwh=0.10,
        active_load_kwh=0.03,
    )
    _unused_wh2, all_load_predicted = ActiveLoadController._predict_unused_budget_wh(
        unused_shared_kwh=0.0,
        shared_energy_kwh=0.15,
        expected_shared_kwh=0.15,
        receiver_import_kwh=0.10,
        active_load_kwh=0.09,
    )
    assert owned_predicted == pytest.approx(80.0)
    assert all_load_predicted == pytest.approx(140.0)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_update_configuration_preserves_ownership(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        load = controller._loads[0]  # noqa: SLF001
        load.owns_switch = True
        load.last_start_ts = dt_util.now()
        load.pending_stop_after_min_on = True
        load.last_integration_context_id = "ctx-123"
        load.interval_energy_wh = 95.0
        load.idle_latched_until_interval_id = "interval-1"
        load.manually_excluded_until_interval_id = "interval-1"
        controller._interval.interval_id = "interval-1"  # noqa: SLF001
        controller._interval.interval_target_wh = 100.0  # noqa: SLF001
        controller._interval.measured_total_wh = 95.0  # noqa: SLF001
        controller._interval.owned_measured_total_wh = 95.0  # noqa: SLF001
        controller.update_configuration(
            [
                ActiveLoadConfig(
                    switch_entity_id="switch.boiler_a",
                    power_sensor_entity_id="sensor.boiler_a_power",
                    priority=0,
                    enabled=True,
                )
            ],
            interval_minutes=15,
        )
        restored = controller._loads[0]  # noqa: SLF001
        assert restored is load
        assert restored.owns_switch is True
        assert restored.last_start_ts == load.last_start_ts
        assert restored.pending_stop_after_min_on is True
        assert restored.last_integration_context_id == "ctx-123"
        assert restored.interval_energy_wh == pytest.approx(95.0)
        assert restored.idle_latched_until_interval_id == "interval-1"
        assert restored.manually_excluded_until_interval_id == "interval-1"
        snapshot = controller.get_snapshot()
        assert snapshot["remaining_wh"] == pytest.approx(5.0)
    finally:
        controller._loads[0].owns_switch = False  # noqa: SLF001
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_update_configuration_turns_off_removed_owned_load(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        load = controller._loads[0]  # noqa: SLF001
        load.owns_switch = True
        with patch.object(
            controller,
            "_async_turn_off_load",
            new=AsyncMock(),
        ) as turn_off:
            controller.update_configuration([], interval_minutes=15)
            await hass.async_block_till_done()
            turn_off.assert_awaited_once_with(
                load, reason="config_removed", force=True
            )
        assert controller._loads == []
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_update_configuration_turns_off_removed_load_when_control_disabled(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager({CONF_ACTIVE_LOAD_CONTROL_ENABLED: False})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        load = controller._loads[0]  # noqa: SLF001
        load.owns_switch = True
        with patch.object(
            controller,
            "_async_turn_off_load",
            new=AsyncMock(),
        ) as turn_off:
            controller.update_configuration([], interval_minutes=15)
            await hass.async_block_till_done()
            turn_off.assert_awaited_once_with(
                load, reason="config_removed", force=True
            )
        assert controller._loads == []
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_restores_estimated_power_from_storage(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    manager._stored_estimates = {"switch.boiler_a": 1800.0}
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    assert controller._loads[0].estimated_power_w == 1800.0  # noqa: SLF001
    await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_restores_and_persists_cumulative_stats(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    manager._stored_cumulative = {
        "mopped_up_wh": 120.0,
        "overshoot_wh": 8.0,
        "undershoot_wh": 3.0,
    }
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    snapshot = controller.get_snapshot()
    assert snapshot["cumulative_mopped_up_wh"] == pytest.approx(120.0)
    assert snapshot["cumulative_overshoot_wh"] == pytest.approx(8.0)
    assert snapshot["cumulative_undershoot_wh"] == pytest.approx(3.0)

    controller._interval.measured_total_wh = 10.0  # noqa: SLF001
    controller._interval.owned_measured_total_wh = 10.0  # noqa: SLF001
    controller._interval.interval_target_wh = 7.0  # noqa: SLF001
    controller._interval.interval_id = "old-interval"  # noqa: SLF001
    controller.notify_processed_interval(0.02)
    assert manager._stored_cumulative["mopped_up_wh"] == pytest.approx(130.0)
    assert manager._stored_cumulative["overshoot_wh"] == pytest.approx(11.0)
    await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_learning_persists_estimated_power(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        load = controller._loads[0]  # noqa: SLF001
        load.switch_is_on = True
        load.last_start_ts = dt_util.now() - timedelta(seconds=60)
        load.measured_power_w = 1500.0
        controller._update_learning(load)  # noqa: SLF001
        await hass.async_block_till_done()
        assert manager._stored_estimates["switch.boiler_a"] == pytest.approx(1500.0)
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_manual_switch_change_releases_ownership(hass: HomeAssistant) -> None:
    manager = _FakeManager(
        {
            CONF_ACTIVE_LOADS: [
                {
                    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: "switch.boiler_a",
                    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: "sensor.boiler_a_power",
                }
            ]
        }
    )
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    hass.states.async_set("switch.boiler_a", "on")
    hass.states.async_set(
        "sensor.boiler_a_power",
        "0",
        attributes={"unit_of_measurement": "W", "device_class": "power"},
    )
    await hass.async_block_till_done()

    # Mimic processed interval creating active interval state.
    controller.notify_processed_interval(unused_shared_kwh=0.5)
    snapshot_before = controller.get_snapshot()
    assert snapshot_before["loads"][0]["owns_switch"] is False

    await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_processed_interval_targets_next_control_window(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        hass.states.async_set("switch.boiler_a", "off")
        hass.states.async_set(
            "sensor.boiler_a_power",
            "1500",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )
        await hass.async_block_till_done()
        controller.notify_processed_interval(unused_shared_kwh=0.1)
        snapshot = controller.get_snapshot()
        assert snapshot["interval_id"] is not None
        assert snapshot["seconds_remaining"] > 0
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_control_disabled_suppresses_switch_calls(hass: HomeAssistant) -> None:
    manager = _FakeManager({CONF_ACTIVE_LOAD_CONTROL_ENABLED: False})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    load = controller._loads[0]  # noqa: SLF001
    await controller._async_turn_on_load(load, reason="test")  # noqa: SLF001
    assert load.owns_switch is False
    await controller._async_turn_off_load(load, reason="test")  # noqa: SLF001
    assert load.owns_switch is False
    await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_learning_includes_manual_on_periods(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    load = controller._loads[0]  # noqa: SLF001

    load.switch_is_on = True
    load.last_start_ts = None
    load.measured_power_w = 1250.0
    controller._update_learning(load)  # noqa: SLF001

    assert load.estimated_power_w == 1250.0
    await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_manual_switch_on_sets_start_timestamp(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    load = controller._loads[0]  # noqa: SLF001
    assert load.last_start_ts is None

    hass.states.async_set("switch.boiler_a", "off")
    await hass.async_block_till_done()
    hass.states.async_set("switch.boiler_a", "on")
    await hass.async_block_till_done()

    assert load.last_start_ts is not None
    await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_unavailable_flicker_keeps_owned_switch(hass: HomeAssistant) -> None:
    """Device blips must not orphan an ALC-owned ON switch as 'manual'."""
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.kitchen_boiler",
                power_sensor_entity_id="sensor.kitchen_boiler_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        hass.states.async_set("switch.kitchen_boiler", "on")
        hass.states.async_set(
            "sensor.kitchen_boiler_power",
            "2200",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )
        await hass.async_block_till_done()

        load = controller._loads[0]  # noqa: SLF001
        load.owns_switch = True
        load.switch_is_on = True
        load.switch_available = True
        controller._interval.interval_id = "interval-1"  # noqa: SLF001

        # Match the soak blip: on → unavailable → off → on (foreign contexts).
        hass.states.async_set("switch.kitchen_boiler", "unavailable")
        await hass.async_block_till_done()
        assert load.owns_switch is True
        assert load.manually_excluded_until_interval_id is None

        hass.states.async_set("switch.kitchen_boiler", "off")
        await hass.async_block_till_done()
        assert load.owns_switch is True
        assert load.manually_excluded_until_interval_id is None

        hass.states.async_set("switch.kitchen_boiler", "on")
        await hass.async_block_till_done()
        assert load.owns_switch is True
        assert load.manually_excluded_until_interval_id is None
        assert load.switch_is_on is True
    finally:
        controller._loads[0].owns_switch = False  # noqa: SLF001
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_real_manual_off_still_releases_ownership(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        hass.states.async_set("switch.boiler_a", "on")
        await hass.async_block_till_done()
        load = controller._loads[0]  # noqa: SLF001
        load.owns_switch = True
        load.switch_is_on = True
        controller._interval.interval_id = "interval-1"  # noqa: SLF001

        hass.states.async_set("switch.boiler_a", "off")
        await hass.async_block_till_done()
        assert load.owns_switch is False
        assert load.manually_excluded_until_interval_id == "interval-1"
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_calibrate_loads_learns_and_restores_state(hass: HomeAssistant) -> None:
    manager = _FakeManager(
        {
            CONF_ACTIVE_LOAD_MIN_ON_SECONDS: 0,
            CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS: 0,
        }
    )
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()

    try:
        hass.states.async_set("switch.boiler_a", "off")
        hass.states.async_set(
            "sensor.boiler_a_power",
            "1450",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )

        async def _turn_on_service(call):
            hass.states.async_set(call.data["entity_id"], "on")

        async def _turn_off_service(call):
            hass.states.async_set(call.data["entity_id"], "off")

        hass.services.async_register("switch", "turn_on", _turn_on_service)
        hass.services.async_register("switch", "turn_off", _turn_off_service)

        with patch(
            "custom_components.energy_sharing.active_loads.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await controller.async_calibrate_loads()
        await hass.async_block_till_done()

        snapshot = controller.get_snapshot()
        load = snapshot["loads"][0]
        assert result["calibrated_loads"] == 1
        assert result["considered_loads"] == 1
        assert snapshot["calibration_in_progress"] is False
        assert snapshot["calibration_last_result"] == result
        assert snapshot["calibration_last_finished_at"] is not None
        assert snapshot["estimated_load_count"] == 1
        assert snapshot["configured_load_count"] == 1
        assert load["estimated_power_w"] == 1450.0
        assert load["switch_available"] is True
        assert manager.notify_calls >= 2
        assert hass.states.get("switch.boiler_a").state == "off"
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_calibrate_loads_keeps_manual_on_load_running(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager(
        {
            CONF_ACTIVE_LOAD_MIN_ON_SECONDS: 0,
            CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS: 0,
        }
    )
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()

    try:
        hass.states.async_set("switch.boiler_a", "on")
        hass.states.async_set(
            "sensor.boiler_a_power",
            "1100",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )
        await hass.async_block_till_done()

        calls = {"on": 0, "off": 0}

        async def _turn_on_service(call):
            calls["on"] += 1
            hass.states.async_set(call.data["entity_id"], "on")

        async def _turn_off_service(call):
            calls["off"] += 1
            hass.states.async_set(call.data["entity_id"], "off")

        hass.services.async_register("switch", "turn_on", _turn_on_service)
        hass.services.async_register("switch", "turn_off", _turn_off_service)

        with patch(
            "custom_components.energy_sharing.active_loads.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await controller.async_calibrate_loads()
        await hass.async_block_till_done()

        snapshot = controller.get_snapshot()
        load = snapshot["loads"][0]
        assert result["calibrated_loads"] == 1
        assert calls["on"] == 0
        assert calls["off"] == 0
        assert load["switch_is_on"] is True
        assert load["estimated_power_w"] == 1100.0
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_calibrate_loads_turns_off_even_if_on_state_delayed(
    hass: HomeAssistant,
) -> None:
    manager = _FakeManager(
        {
            CONF_ACTIVE_LOAD_MIN_ON_SECONDS: 0,
            CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS: 0,
        }
    )
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()

    try:
        hass.states.async_set("switch.boiler_a", "off")
        hass.states.async_set(
            "sensor.boiler_a_power",
            "1400",
            attributes={"unit_of_measurement": "W", "device_class": "power"},
        )
        calls = {"off": 0}

        async def _turn_on_service(call):
            # Simulate state propagation lag: no immediate state update.
            _ = call

        async def _turn_off_service(call):
            calls["off"] += 1
            hass.states.async_set(call.data["entity_id"], "off")

        hass.services.async_register("switch", "turn_on", _turn_on_service)
        hass.services.async_register("switch", "turn_off", _turn_off_service)

        with patch(
            "custom_components.energy_sharing.active_loads.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await controller.async_calibrate_loads()
        await hass.async_block_till_done()

        assert result["considered_loads"] == 1
        assert result["calibrated_loads"] == 0
        assert calls["off"] == 1
    finally:
        await controller.async_unload()


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_apply_control_skipped_during_calibration(hass: HomeAssistant) -> None:
    manager = _FakeManager({})
    controller = ActiveLoadController(
        hass,
        manager,
        [
            ActiveLoadConfig(
                switch_entity_id="switch.boiler_a",
                power_sensor_entity_id="sensor.boiler_a_power",
                priority=0,
                enabled=True,
            )
        ],
        interval_minutes=15,
    )
    await controller.async_setup()
    try:
        load = controller._loads[0]  # noqa: SLF001
        controller._interval.interval_end = dt_util.now() + timedelta(minutes=5)  # noqa: SLF001
        controller._interval.interval_target_wh = 200.0  # noqa: SLF001
        controller._calibration_in_progress = True  # noqa: SLF001
        with patch.object(
            controller,
            "_async_turn_on_load",
            new=AsyncMock(),
        ) as mocked_turn_on:
            await controller._apply_control()  # noqa: SLF001
            mocked_turn_on.assert_not_called()
        assert load.allocated_target_wh == 0.0
    finally:
        await controller.async_unload()
