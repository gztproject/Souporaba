"""Tests for active load runtime helpers."""

from __future__ import annotations

from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from custom_components.energy_sharing.active_loads import (
    ActiveLoadConfig,
    ActiveLoadController,
    parse_power_watts,
)
from custom_components.energy_sharing.const import (
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
)


class _FakeManager:
    def __init__(self, options: dict) -> None:
        self._options = options

    def get_option(self, key: str, default=None):
        return self._options.get(key, default)


def test_parse_power_watts_w_and_kw() -> None:
    assert parse_power_watts("100", "W") == 100.0
    assert parse_power_watts("1.5", "kW") == 1500.0
    assert parse_power_watts("bad", "W") is None
    assert parse_power_watts("-1", "W") is None


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
