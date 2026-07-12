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
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PROCESSING_DELAY,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_RETRY_INTERVAL,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    CONF_SOURCE_FRESHNESS_TOLERANCE,
    CONFIG_ENTRY_VERSION,
    DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RETRY_INTERVAL,
    DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable custom integrations for every test."""


@pytest.fixture(autouse=True)
def set_ljubljana_timezone(hass: HomeAssistant) -> None:
    hass.config.time_zone = "Europe/Ljubljana"


@pytest.fixture(autouse=True)
def disable_scheduler(set_ljubljana_timezone: None) -> Generator[None]:
    with patch(
        "custom_components.energy_sharing.manager.EnergySharingManager._schedule_next_processing"
    ):
        yield


@pytest.fixture
def receiver_import_total_entity() -> str:
    return "sensor.test_receiver_import_total"


@pytest.fixture
def shared_energy_total_entity() -> str:
    return "sensor.test_shared_energy_total"


@pytest.fixture
def provider_export_total_entity() -> str:
    return "sensor.test_provider_export_total"


@pytest.fixture
def interval_end() -> datetime:
    return datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )


def cumulative_state(
    entity_id: str,
    total: float,
    unit: str = UnitOfEnergy.KILO_WATT_HOUR,
    *,
    last_updated: datetime | None = None,
) -> dict[str, Any]:
    attrs = {"unit_of_measurement": unit}
    return {
        "entity_id": entity_id,
        "state": str(total),
        "attributes": attrs,
        "last_updated": last_updated,
    }


def set_cumulative_sources(
    hass: HomeAssistant,
    *,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    receiver_total: float,
    shared_total: float,
    provider_export_total_entity: str | None = None,
    provider_total: float | None = None,
    unit: str = UnitOfEnergy.KILO_WATT_HOUR,
    last_updated: datetime | None = None,
) -> None:
    hass.states.async_set(
        receiver_import_total_entity,
        str(receiver_total),
        attributes={"unit_of_measurement": unit},
    )
    hass.states.async_set(
        shared_energy_total_entity,
        str(shared_total),
        attributes={"unit_of_measurement": unit},
    )
    if provider_export_total_entity is not None and provider_total is not None:
        hass.states.async_set(
            provider_export_total_entity,
            str(provider_total),
            attributes={"unit_of_measurement": unit},
        )


@pytest.fixture
def mock_config_entry_percentage_only(
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> MockConfigEntry:
    return MockConfigEntry(
        version=CONFIG_ENTRY_VERSION,
        domain=DOMAIN,
        title="Energy Sharing",
        data={
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
        },
        options={
            CONF_FIXED_ALLOCATION_PERCENTAGE: DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
            CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
            CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
            CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
            CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
            CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
        },
        unique_id=f"{receiver_import_total_entity}|{shared_energy_total_entity}",
    )


@pytest.fixture
def mock_config_entry_export_only(
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> MockConfigEntry:
    return MockConfigEntry(
        version=CONFIG_ENTRY_VERSION,
        domain=DOMAIN,
        title="Energy Sharing",
        data={
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
        },
        options={
            CONF_PROVIDER_EXPORT_TOTAL_SOURCE: provider_export_total_entity,
            CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
            CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
            CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
            CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
            CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
        },
        unique_id=f"{receiver_import_total_entity}|{shared_energy_total_entity}",
    )


@pytest.fixture
def mock_config_entry_export_and_percentage(
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> MockConfigEntry:
    return MockConfigEntry(
        version=CONFIG_ENTRY_VERSION,
        domain=DOMAIN,
        title="Energy Sharing",
        data={
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver_import_total_entity,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared_energy_total_entity,
        },
        options={
            CONF_PROVIDER_EXPORT_TOTAL_SOURCE: provider_export_total_entity,
            CONF_FIXED_ALLOCATION_PERCENTAGE: DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
            CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
            CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
            CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
            CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
            CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
        },
        unique_id=f"{receiver_import_total_entity}|{shared_energy_total_entity}",
    )


@pytest.fixture
async def setup_percentage_only(
    hass: HomeAssistant,
    mock_config_entry_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> MockConfigEntry:
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
    )
    mock_config_entry_percentage_only.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_percentage_only.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry_percentage_only


@pytest.fixture
async def setup_export_and_percentage(
    hass: HomeAssistant,
    mock_config_entry_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> MockConfigEntry:
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_import_total_entity,
        shared_energy_total_entity=shared_energy_total_entity,
        receiver_total=100.0,
        shared_total=10.0,
        provider_export_total_entity=provider_export_total_entity,
        provider_total=200.0,
    )
    mock_config_entry_export_and_percentage.add_to_hass(hass)
    await hass.config_entries.async_setup(
        mock_config_entry_export_and_percentage.entry_id
    )
    await hass.async_block_till_done()
    return mock_config_entry_export_and_percentage
