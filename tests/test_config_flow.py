"""Tests for the Energy Sharing config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_ACTIVE_LOADS,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    DOMAIN,
)


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_config_flow_percentage_only(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    hass.states.async_set(
        receiver_import_total_entity,
        "100",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        "10",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_FIXED_ALLOCATION_PERCENTAGE] == 7.0


async def test_config_flow_export_and_percentage(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    for entity, total in (
        (receiver_import_total_entity, "100"),
        (shared_energy_total_entity, "10"),
        (provider_export_total_entity, "200"),
    ):
        hass.states.async_set(
            entity,
            total,
            attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
        )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
            CONF_PROVIDER_EXPORT_TOTAL_SOURCE: provider_export_total_entity,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_config_flow_rejects_missing_percentage_and_export(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    hass.states.async_set(
        receiver_import_total_entity,
        "100",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        "10",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "percentage_or_export_required"


async def test_config_flow_rejects_duplicate_sources(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
) -> None:
    hass.states.async_set(
        receiver_import_total_entity,
        "100",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "duplicate_sources"


async def test_config_flow_rejects_zero_percentage(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    hass.states.async_set(
        receiver_import_total_entity,
        "100",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        "10",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 0,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_FIXED_ALLOCATION_PERCENTAGE] == "percentage_invalid"


async def test_config_flow_rejects_unsupported_unit(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    hass.states.async_set(
        receiver_import_total_entity,
        "100",
        attributes={"unit_of_measurement": "bananas"},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        "10",
        attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["receiver_import"] == "unsupported_energy_unit"


async def test_options_flow_active_load_switch_selection(
    hass: HomeAssistant,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Energy Sharing",
        data={
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
        },
        options={CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0, CONF_ACTIVE_LOADS: []},
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        receiver_import_total_entity,
        "100",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        "10",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set("switch.boiler_a", "off")
    hass.states.async_set(
        "sensor.boiler_a_power",
        "0",
        {"unit_of_measurement": "W", "device_class": "power"},
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0,
            "active_load_switches": ["switch.boiler_a"],
        },
    )
    assert result["type"] in (FlowResultType.FORM, FlowResultType.CREATE_ENTRY)
