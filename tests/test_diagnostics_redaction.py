"""The diagnostics download must not disclose household configuration.

Home Assistant's device page downloads config-entry diagnostics when the
integration does not implement device diagnostics. This file is the document
an administrator attaches to a support request. Entry data and options are
redacted; the same download must not put those values back through the
config-entry unique id or the runtime snapshot.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from freezegun import freeze_time
from homeassistant.components.diagnostics.const import REDACTED
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.energy_sharing.const import (
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    DOMAIN,
)

RECEIVER = "sensor.household_receiver_meter_9f3a"
SHARED = "sensor.household_shared_meter_9f3a"
PROVIDER = "sensor.household_provider_meter_9f3a"
SWITCH = "switch.household_water_heater_9f3a"
POWER = "sensor.household_water_heater_power_9f3a"
# Placeholder standing in for an account or device id carried on a source sensor.
ACCOUNT_IDENTIFIER = "acct-placeholder-9f3a"
ALLOCATION_PERCENTAGE = 37.25

BASE_RECEIVER = 100.625
BASE_SHARED = 10.375
BASE_PROVIDER = 200.125
SETTLED_RECEIVER = 101.25
SETTLED_SHARED = 10.75
SETTLED_PROVIDER = 200.25
RESET_RECEIVER = 80.5


@pytest.fixture(scope="session", autouse=True)
def _pycares_shutdown_thread_is_process_wide() -> None:
    """The HTTP client resolver starts one process-wide pycares thread.

    Home Assistant 2025.1.4 creates it from ``aiohttp.resolver.AsyncResolver``
    while serving the diagnostics download. Start it before the test so the
    cleanup check does not treat that resolver thread as a leak.
    """
    from pycares import _shutdown_manager

    _shutdown_manager.start()


def _set_meters(
    hass: HomeAssistant,
    *,
    receiver: float,
    shared: float,
    provider: float,
) -> None:
    """Publish cumulative meter states, including an identifier attribute."""
    for entity_id, total in (
        (RECEIVER, receiver),
        (SHARED, shared),
        (PROVIDER, provider),
    ):
        hass.states.async_set(
            entity_id,
            str(total),
            {
                "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
                "account_identifier": ACCOUNT_IDENTIFIER,
            },
        )


def _add_number(found: set[str], value: Any) -> None:
    """Record a stored energy or percentage value that must not be exported."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float) and float(value) == 0.0:
        return
    if isinstance(value, int | float):
        found.add(json.dumps(value))


def _stored_secrets(manager: Any) -> set[str]:
    """Secrets the running integration has stored and the download must omit."""
    found = {
        RECEIVER,
        SHARED,
        PROVIDER,
        SWITCH,
        POWER,
        f"{RECEIVER}|{SHARED}",
        ACCOUNT_IDENTIFIER,
        json.dumps(ALLOCATION_PERCENTAGE),
    }
    data = manager.data
    snapshot = data.previous_snapshot
    if snapshot is not None:
        _add_number(found, snapshot.receiver_import_total_kwh)
        _add_number(found, snapshot.shared_energy_total_kwh)
        _add_number(found, snapshot.provider_export_total_kwh)
    interval = data.last_interval
    if interval is not None:
        for key, value in interval.to_dict().items():
            if key.endswith("_kwh") or key == "fixed_allocation_percentage":
                _add_number(found, value)
    for value in (
        data.cumulative_receiver_import,
        data.cumulative_shared_energy,
        data.cumulative_provider_export,
        data.cumulative_expected_shared,
        data.cumulative_used,
        data.cumulative_unused,
        data.cumulative_billable_energy,
    ):
        _add_number(found, value)
    reset = data.last_source_reset
    if reset is not None:
        found.add(reset.entity_id)
        _add_number(found, reset.previous_total_kwh)
        _add_number(found, reset.new_total_kwh)
    for entity_id in (RECEIVER, SHARED, PROVIDER):
        state = manager.hass.states.get(entity_id)
        assert state is not None
        found.add(state.state)
        identifier = state.attributes.get("account_identifier")
        if identifier is not None:
            found.add(str(identifier))
    return {item for item in found if item}


async def test_diagnostics_download_hides_meters_loads_and_energy(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
) -> None:
    """Download the same file the device page saves, and require redaction.

    The device page calls ``/api/diagnostics/config_entry/<entry_id>`` when
    ``handlers.device`` is false. That response is what a later reader of the
    attached file sees.
    """
    with freeze_time("2026-07-12 15:00:10+02:00"):
        _set_meters(
            hass,
            receiver=BASE_RECEIVER,
            shared=BASE_SHARED,
            provider=BASE_PROVIDER,
        )
        hass.states.async_set(SWITCH, "off")
        hass.states.async_set(
            POWER,
            "0",
            {"unit_of_measurement": "W", "device_class": "power"},
        )

        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        created = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            user_input={
                "name": "Energy Sharing",
                CONF_RECEIVER_IMPORT_TOTAL_SOURCE: RECEIVER,
                CONF_SHARED_ENERGY_TOTAL_SOURCE: SHARED,
                CONF_PROVIDER_EXPORT_TOTAL_SOURCE: PROVIDER,
                CONF_FIXED_ALLOCATION_PERCENTAGE: ALLOCATION_PERCENTAGE,
            },
        )
        assert created["type"] == FlowResultType.CREATE_ENTRY
        entry = created["result"]
        assert entry.unique_id == f"{RECEIVER}|{SHARED}"
        await hass.async_block_till_done()

        options = await hass.config_entries.options.async_init(entry.entry_id)
        options = await hass.config_entries.options.async_configure(
            options["flow_id"],
            user_input={
                "name": "Energy Sharing",
                CONF_PROVIDER_EXPORT_TOTAL_SOURCE: PROVIDER,
                CONF_FIXED_ALLOCATION_PERCENTAGE: ALLOCATION_PERCENTAGE,
                "active_load_switches": [SWITCH],
            },
        )
        assert options["type"] == FlowResultType.FORM
        assert options["step_id"] == "active_load_sensors"
        options = await hass.config_entries.options.async_configure(
            options["flow_id"],
            user_input={SWITCH: POWER},
        )
        assert options["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        loads = entry.options[CONF_ACTIVE_LOADS]
        assert loads[0][CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID] == SWITCH
        assert loads[0][CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID] == POWER

        manager = entry.runtime_data.manager
        assert await manager.async_process_now() == "baseline_initialized"
        _set_meters(
            hass,
            receiver=SETTLED_RECEIVER,
            shared=SETTLED_SHARED,
            provider=SETTLED_PROVIDER,
        )
        assert await manager.async_process_now() == "processed"
        assert manager.data.last_interval is not None
        assert manager.data.cumulative_receiver_import != 0

    with freeze_time("2026-07-12 15:15:10+02:00"):
        _set_meters(
            hass,
            receiver=RESET_RECEIVER,
            shared=SETTLED_SHARED,
            provider=SETTLED_PROVIDER,
        )
        # The first drop is held until the source-wait window closes.
        assert (
            await manager.async_process_now()
            == "retrying:counter_reset:receiver_import"
        )

    with freeze_time("2026-07-12 15:16:11+02:00"):
        _set_meters(
            hass,
            receiver=RESET_RECEIVER,
            shared=SETTLED_SHARED,
            provider=SETTLED_PROVIDER,
        )
        assert (
            await manager.async_process_now()
            == "skipped:counter_reset:receiver_import"
        )

    assert manager.data.last_source_reset is not None
    assert manager.data.last_source_reset.entity_id == RECEIVER
    active = manager.get_diagnostics_snapshot()["active_loads"]
    assert active is not None
    assert active["loads"][0]["switch_entity_id"] == SWITCH
    assert active["loads"][0]["power_sensor_entity_id"] == POWER

    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
    assert response.status == 200
    assert "attachment" in response.headers.get("Content-Disposition", "")
    body = await response.text()
    downloaded = json.loads(body)
    data = downloaded["data"]
    # Search the integration payload, not Home Assistant's setup-time wrapper.
    data_body = body.split('"data":', 1)[1]

    assert data["entry"]["title"] == "Energy Sharing"
    assert data["entry"]["data"][CONF_RECEIVER_IMPORT_TOTAL_SOURCE] == REDACTED
    assert data["entry"]["data"][CONF_SHARED_ENERGY_TOTAL_SOURCE] == REDACTED
    assert data["entry"]["options"][CONF_PROVIDER_EXPORT_TOTAL_SOURCE] == REDACTED
    assert data["entry"]["options"][CONF_FIXED_ALLOCATION_PERCENTAGE] == REDACTED
    assert data["entry"]["options"][CONF_ACTIVE_LOADS] == REDACTED

    leaked = sorted(
        secret for secret in _stored_secrets(manager) if secret in data_body
    )
    assert leaked == []
