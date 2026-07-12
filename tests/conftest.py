"""Test fixtures for Energy Sharing."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_ALLOCATION_PERCENTAGE_MODE,
    CONF_ALLOCATION_PERCENTAGE_SOURCE,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PROCESSING_DELAY,
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_RESET_TOLERANCE,
    CONF_RETRY_INTERVAL,
    CONFIG_ENTRY_VERSION,
    DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RESET_TOLERANCE,
    DEFAULT_RETRY_INTERVAL,
    DOMAIN,
    PERCENTAGE_MODE_ENTITY,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable custom integrations for every test."""


@pytest.fixture(autouse=True)
def set_ljubljana_timezone(hass: HomeAssistant) -> None:
    """Use the expected settlement timezone in tests."""
    hass.config.time_zone = "Europe/Ljubljana"


@pytest.fixture(autouse=True)
def disable_scheduler(set_ljubljana_timezone: None) -> Generator[None]:
    """Disable automatic scheduling during tests."""
    with patch(
        "custom_components.energy_sharing.manager.EnergySharingManager._schedule_next_processing"
    ):
        yield


@pytest.fixture
def provider_export_entity() -> str:
    """Return a test provider export entity ID."""
    return "sensor.test_provider_export_15min"


@pytest.fixture
def receiver_import_entity() -> str:
    """Return a test receiver import entity ID."""
    return "sensor.test_receiver_import_15min"


@pytest.fixture
def reported_allocation_entity() -> str:
    """Return a test reported allocation entity ID."""
    return "sensor.test_reported_allocation_15min"


@pytest.fixture
def percentage_entity() -> str:
    """Return a test percentage entity ID."""
    return "input_number.test_share_percentage"


def make_utility_meter_state(
    entity_id: str,
    last_period: float,
    last_reset: datetime,
    unit: str = UnitOfEnergy.KILO_WATT_HOUR,
) -> dict[str, Any]:
    """Build utility meter state attributes."""
    return {
        "entity_id": entity_id,
        "state": "0",
        "attributes": {
            "last_period": last_period,
            "last_reset": last_reset.isoformat(),
            "unit_of_measurement": unit,
        },
    }


def make_percentage_state(entity_id: str, value: float) -> dict[str, Any]:
    """Build a percentage entity state."""
    return {
        "entity_id": entity_id,
        "state": str(value),
        "attributes": {"unit_of_measurement": "%"},
    }


@pytest.fixture
def interval_end() -> datetime:
    """Return a standard completed interval end timestamp."""
    return datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )


@pytest.fixture
def mock_config_entry(
    provider_export_entity: str,
    receiver_import_entity: str,
    percentage_entity: str,
) -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        version=CONFIG_ENTRY_VERSION,
        domain=DOMAIN,
        title="Energy Sharing",
        data={
            CONF_PROVIDER_EXPORT_SOURCE: provider_export_entity,
            CONF_RECEIVER_IMPORT_SOURCE: receiver_import_entity,
        },
        options={
            CONF_ALLOCATION_PERCENTAGE_MODE: PERCENTAGE_MODE_ENTITY,
            CONF_ALLOCATION_PERCENTAGE_SOURCE: percentage_entity,
            CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
            CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
            CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
            CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
            CONF_RESET_TOLERANCE: DEFAULT_RESET_TOLERANCE,
            CONF_FIXED_ALLOCATION_PERCENTAGE: DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
            "allow_percentage_above_100": False,
        },
        unique_id=f"{provider_export_entity}|{receiver_import_entity}",
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    provider_export_entity: str,
    receiver_import_entity: str,
    percentage_entity: str,
    interval_end: datetime,
) -> MockConfigEntry:
    """Set up the integration with default source entities."""
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
        percentage_entity, "7", attributes={"unit_of_measurement": "%"}
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def set_interval_sources(
    hass: HomeAssistant,
    *,
    provider_export_entity: str,
    receiver_import_entity: str,
    interval_end: datetime,
    provider_export_kwh: float = 10.0,
    receiver_import_kwh: float = 1.0,
    reported_allocation_entity: str | None = None,
    reported_allocated_kwh: float | None = None,
    unit: str = UnitOfEnergy.KILO_WATT_HOUR,
) -> None:
    """Set synchronized interval source entity states."""
    hass.states.async_set(
        provider_export_entity,
        "0",
        attributes={
            "last_period": provider_export_kwh,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": unit,
        },
    )
    hass.states.async_set(
        receiver_import_entity,
        "0",
        attributes={
            "last_period": receiver_import_kwh,
            "last_reset": interval_end.isoformat(),
            "unit_of_measurement": unit,
        },
    )
    if reported_allocation_entity is not None and reported_allocated_kwh is not None:
        hass.states.async_set(
            reported_allocation_entity,
            "0",
            attributes={
                "last_period": reported_allocated_kwh,
                "last_reset": interval_end.isoformat(),
                "unit_of_measurement": unit,
            },
        )
