"""Tests for the Energy Sharing config flow."""

from __future__ import annotations

from datetime import datetime

from homeassistant import config_entries
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_ALLOCATION_PERCENTAGE_MODE,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_REPORTED_ALLOCATION_SOURCE,
    DOMAIN,
    PERCENTAGE_MODE_ENTITY,
    PERCENTAGE_MODE_FIXED,
)


async def _start_user_flow(hass: HomeAssistant):
    """Start the user config flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_config_flow_success(
    hass: HomeAssistant,
    provider_export_entity: str,
    receiver_import_entity: str,
    percentage_entity: str,
    interval_end: datetime,
) -> None:
    """Test config flow succeeds with valid entities."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(percentage_entity, "7")

    result = await _start_user_flow(hass)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_PROVIDER_EXPORT_SOURCE: provider_export_entity,
            CONF_RECEIVER_IMPORT_SOURCE: receiver_import_entity,
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: percentage_entity,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROVIDER_EXPORT_SOURCE] == provider_export_entity


async def test_config_flow_duplicate_rejected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    percentage_entity: str,
    interval_end: datetime,
) -> None:
    """Test duplicate configuration is rejected."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(percentage_entity, "7")
    mock_config_entry.add_to_hass(hass)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_PROVIDER_EXPORT_SOURCE: provider_export_entity,
            CONF_RECEIVER_IMPORT_SOURCE: receiver_import_entity,
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: percentage_entity,
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_settings(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test options flow updates settings."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing Updated",
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: setup_integration.options[
                CONF_ALLOCATION_PERCENTAGE_SOURCE
            ],
            "interval_minutes": 15,
            "processing_delay": 12,
            "max_wait": 90,
            "retry_interval": 4,
            "reset_tolerance": 6,
            "allocation_tolerance_kwh": 0.02,
            "allocation_tolerance_pct": 3.0,
            "reconciliation_failure_mode": "warn",
            "allow_percentage_above_100": True,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(setup_integration.entry_id)
    assert entry is not None
    assert entry.title == "Energy Sharing Updated"
    assert entry.options["processing_delay"] == 12


async def test_config_flow_invalid_unit_rejected(
    hass: HomeAssistant,
    provider_export_entity: str,
    receiver_import_entity: str,
    percentage_entity: str,
    interval_end: datetime,
) -> None:
    """Test invalid units are rejected."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": "bananas",
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(percentage_entity, "7")

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_PROVIDER_EXPORT_SOURCE: provider_export_entity,
            CONF_RECEIVER_IMPORT_SOURCE: receiver_import_entity,
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: percentage_entity,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["provider_export"] == "unsupported_energy_unit"


async def test_config_flow_fixed_percentage_mode(
    hass: HomeAssistant,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
) -> None:
    """Test config flow with fixed percentage mode."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_PROVIDER_EXPORT_SOURCE: provider_export_entity,
            CONF_RECEIVER_IMPORT_SOURCE: receiver_import_entity,
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_FIXED,
            CONF_FIXED_ALLOCATION_PERCENTAGE: 7.0,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_FIXED_ALLOCATION_PERCENTAGE] == 7.0


async def test_config_flow_optional_reported_source(
    hass: HomeAssistant,
    provider_export_entity: str,
    receiver_import_entity: str,
    reported_allocation_entity: str,
    percentage_entity: str,
    interval_end: datetime,
) -> None:
    """Test config flow accepts optional reported allocation source."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": 10.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        reported_allocation_entity,
        "0",
        attributes={
            "last_period": 0.7,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(percentage_entity, "7")

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_PROVIDER_EXPORT_SOURCE: provider_export_entity,
            CONF_RECEIVER_IMPORT_SOURCE: receiver_import_entity,
            CONF_REPORTED_ALLOCATION_SOURCE: reported_allocation_entity,
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: percentage_entity,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert (
        result["options"][CONF_REPORTED_ALLOCATION_SOURCE]
        == reported_allocation_entity
    )
