"""Button platform for Energy Sharing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EnergySharingConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL


@dataclass(frozen=True, kw_only=True)
class EnergySharingButtonDescription(ButtonEntityDescription):
    """Describe an Energy Sharing button entity."""


BUTTONS: tuple[EnergySharingButtonDescription, ...] = (
    EnergySharingButtonDescription(
        key="calibrate_active_loads",
        translation_key="calibrate_active_loads",
        icon="mdi:tune-variant",
    ),
)


async def async_setup_entry(
    hass: Any,
    entry: EnergySharingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    async_add_entities(
        [EnergySharingButton(entry, manager, description) for description in BUTTONS]
    )


class EnergySharingButton(ButtonEntity):
    """Representation of an Energy Sharing button."""

    _attr_has_entity_name = True
    entity_description: EnergySharingButtonDescription

    def __init__(
        self,
        entry: EnergySharingConfigEntry,
        manager: Any,
        description: EnergySharingButtonDescription,
    ) -> None:
        self.entity_description = description
        self._entry = entry
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=manager.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._attr_translation_key = description.translation_key

    async def async_press(self) -> None:
        await self._manager.async_calibrate_active_loads()
