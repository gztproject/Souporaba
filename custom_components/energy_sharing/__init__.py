"""The Energy Sharing integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN as DOMAIN
from .manager import EnergySharingManager
from .models import EnergySharingRuntimeData

PLATFORMS: list[Platform] = [Platform.SENSOR]

type EnergySharingConfigEntry = ConfigEntry[EnergySharingRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Energy Sharing integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EnergySharingConfigEntry) -> bool:
    """Set up Energy Sharing from a config entry."""
    manager = EnergySharingManager(hass, entry)
    await manager.async_setup()

    entry.runtime_data = EnergySharingRuntimeData(manager=manager)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergySharingConfigEntry) -> bool:
    """Unload an Energy Sharing config entry."""
    if entry.runtime_data is not None:
        await entry.runtime_data.manager.async_unload()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: EnergySharingConfigEntry
) -> None:
    """Handle options update."""
    if entry.runtime_data is not None:
        manager = entry.runtime_data.manager
        manager.entry = entry
        manager.async_reconfigure()
