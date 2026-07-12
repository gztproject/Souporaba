"""Tests for the Energy Sharing config flow."""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant import config_entries
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_FIXED_PERCENTAGE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_PERCENTAGE_ENTITY,
    CONF_PERCENTAGE_MODE,
    CONF_SHARED_ENERGY_ENTITY,
    DOMAIN,
    PERCENTAGE_MODE_ENTITY,
    PERCENTAGE_MODE_FIXED,
)


async def _start_user_flow(hass: HomeAssistant):
    """Start the user config flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


@pytest.fixture
def source_states(
    grid_import_entity: str,
    shared_energy_entity: str,
    percentage_entity: str,
) -> datetime:
    """Create valid source entity states."""
    interval_end = datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    return interval_end


async def test_config_flow_success(
    hass: HomeAssistant,
    grid_import_entity: str,
    shared_energy_entity: str,
    percentage_entity: str,
    source_states: datetime,
) -> None:
    """Test config flow succeeds with valid entities."""
    interval_end = source_states
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
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
            CONF_GRID_IMPORT_ENTITY: grid_import_entity,
            CONF_SHARED_ENERGY_ENTITY: shared_energy_entity,
            CONF_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_PERCENTAGE_ENTITY: percentage_entity,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Energy Sharing"
    assert result["data"][CONF_GRID_IMPORT_ENTITY] == grid_import_entity


async def test_config_flow_duplicate_rejected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    grid_import_entity: str,
    shared_energy_entity: str,
    percentage_entity: str,
    source_states: datetime,
) -> None:
    """Test duplicate configuration is rejected."""
    interval_end = source_states
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
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
            CONF_GRID_IMPORT_ENTITY: grid_import_entity,
            CONF_SHARED_ENERGY_ENTITY: shared_energy_entity,
            CONF_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_PERCENTAGE_ENTITY: percentage_entity,
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
            "interval_minutes": 15,
            "processing_delay": 12,
            "max_wait": 90,
            "retry_interval": 4,
            "reset_tolerance": 6,
            "allow_percentage_above_100": True,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(setup_integration.entry_id)
    assert entry is not None
    assert entry.title == "Energy Sharing Updated"
    assert "processing_delay" in entry.options
    assert entry.options["processing_delay"] == 12
    assert entry.options["max_wait"] == 90


async def test_config_flow_invalid_unit_rejected(
    hass: HomeAssistant,
    grid_import_entity: str,
    shared_energy_entity: str,
    percentage_entity: str,
    source_states: datetime,
) -> None:
    """Test invalid units are rejected."""
    interval_end = source_states
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": "bananas",
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
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
            CONF_GRID_IMPORT_ENTITY: grid_import_entity,
            CONF_SHARED_ENERGY_ENTITY: shared_energy_entity,
            CONF_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_PERCENTAGE_ENTITY: percentage_entity,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["grid_import"] == "invalid_utility_meter"


async def test_config_flow_fixed_percentage_mode(
    hass: HomeAssistant,
    grid_import_entity: str,
    shared_energy_entity: str,
    source_states: datetime,
) -> None:
    """Test config flow with fixed percentage mode."""
    interval_end = source_states
    hass.states.async_set(
        grid_import_entity,
        "0",
        attributes={
            "last_period": 1.0,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        shared_energy_entity,
        "0",
        attributes={
            "last_period": 0.2,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Energy Sharing",
            CONF_GRID_IMPORT_ENTITY: grid_import_entity,
            CONF_SHARED_ENERGY_ENTITY: shared_energy_entity,
            CONF_PERCENTAGE_MODE: PERCENTAGE_MODE_FIXED,
            CONF_FIXED_PERCENTAGE: 7.0,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_FIXED_PERCENTAGE] == 7.0
