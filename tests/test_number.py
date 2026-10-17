"""Tests for the allocation percentage number entity."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    DOMAIN,
)


async def test_number_updates_options(
    hass: HomeAssistant,
    setup_export_and_percentage: MockConfigEntry,
) -> None:
    entry = setup_export_and_percentage
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_fixed_allocation_percentage"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(7.0)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": 8.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_FIXED_ALLOCATION_PERCENTAGE] == 8.5
    updated = hass.states.get(entity_id)
    assert updated is not None
    assert float(updated.state) == pytest.approx(8.5)
