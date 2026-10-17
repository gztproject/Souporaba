"""Number platform for Energy Sharing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EnergySharingConfigEntry
from .const import (
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    DOMAIN,
    MANUFACTURER,
    MAX_ALLOCATION_PERCENTAGE,
    MIN_ALLOCATION_PERCENTAGE,
    MODEL,
)


async def async_setup_entry(
    hass: Any,
    entry: EnergySharingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    async_add_entities([FixedAllocationPercentageNumber(entry, manager)])


class FixedAllocationPercentageNumber(NumberEntity):
    """Config number for the contractual Moj Elektro allocation percentage."""

    _attr_has_entity_name = True
    _attr_translation_key = "fixed_allocation_percentage"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_ALLOCATION_PERCENTAGE
    _attr_native_max_value = MAX_ALLOCATION_PERCENTAGE
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:percent"

    def __init__(self, entry: EnergySharingConfigEntry, manager: Any) -> None:
        self._entry = entry
        self._manager = manager
        self._unsub_update: Callable[[], None] | None = None
        self._attr_unique_id = f"{entry.entry_id}_fixed_allocation_percentage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=manager.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        self._unsub_update = self._manager.add_update_listener(
            self._handle_manager_update
        )
        self._update_from_manager()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None

    @callback
    def _handle_manager_update(self) -> None:
        self._update_from_manager()
        self.async_write_ha_state()

    @callback
    def _update_from_manager(self) -> None:
        self._attr_native_value = self._manager.fixed_allocation_percentage
        self._attr_available = True

    async def async_set_native_value(self, value: float) -> None:
        options = {
            **self._entry.options,
            CONF_FIXED_ALLOCATION_PERCENTAGE: float(value),
        }
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self._attr_native_value = float(value)
        self.async_write_ha_state()
