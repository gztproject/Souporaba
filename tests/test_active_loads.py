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
    assert parse_power_watts("-1", "W") is None


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
