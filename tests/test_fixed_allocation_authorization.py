"""Authorization for the contractual allocation percentage number.

These tests are the spec for a missing admin check. They fail while a
signed-in non-admin who can control the number can change the stored share.
"""

from __future__ import annotations

import traceback
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.models import User
from homeassistant.auth.permissions.const import CAT_ENTITIES, POLICY_CONTROL
from homeassistant.components.number.device_action import async_call_action_from_config
from homeassistant.const import EntityCategory
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    CONF_ACTIVE_LOAD_ENABLED,
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_PRIORITY,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PROCESSING_DELAY,
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
from tests.conftest import set_cumulative_sources

BOILER_SWITCH = "switch.boiler_contactor"
BOILER_POWER = "sensor.boiler_contactor_power"
ORIGINAL_SHARE = DEFAULT_FIXED_ALLOCATION_PERCENTAGE
OTHER_SHARE = 20.0


def _options(share: float, *, with_load: bool) -> dict[str, Any]:
    options: dict[str, Any] = {
        CONF_FIXED_ALLOCATION_PERCENTAGE: share,
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
        CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
        CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
        CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
    }
    if with_load:
        options[CONF_ACTIVE_LOADS] = [
            {
                CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: BOILER_SWITCH,
                CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: BOILER_POWER,
                CONF_ACTIVE_LOAD_PRIORITY: 0,
                CONF_ACTIVE_LOAD_ENABLED: True,
            }
        ]
    return options


def _entry(
    *,
    receiver: str,
    shared: str,
    share: float,
    with_load: bool,
    title: str,
) -> MockConfigEntry:
    return MockConfigEntry(
        version=CONFIG_ENTRY_VERSION,
        domain=DOMAIN,
        title=title,
        data={
            CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver,
            CONF_SHARED_ENERGY_TOTAL_SOURCE: shared,
        },
        options=_options(share, with_load=with_load),
        unique_id=f"{receiver}|{shared}",
    )


async def _async_setup_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    receiver: str,
    shared: str,
) -> None:
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver,
        shared_energy_total_entity=shared,
        receiver_total=100.0,
        shared_total=10.0,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _number_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_fixed_allocation_percentage"
    )
    assert entity_id is not None
    return entity_id


async def _async_household_users(
    hass: HomeAssistant,
) -> tuple[User, User]:
    """Return an owner admin and a non-admin member of the Users group.

    The first non-system user is the owner. The member is the default
    household account: active, not an administrator, and allowed to control
    every entity.
    """
    owner = await hass.auth.async_create_user("Owner")
    member = await hass.auth.async_create_user(
        "Household member", group_ids=[GROUP_ID_USER]
    )
    assert owner.is_owner is True
    assert owner.is_admin is True
    assert member.is_owner is False
    assert member.is_active is True
    assert member.is_admin is False
    return owner, member


def _assert_controls(
    user: User, entity_id: str, *, allowed: bool
) -> None:
    assert user.permissions.check_entity(entity_id, POLICY_CONTROL) is allowed


async def _async_set_share(
    hass: HomeAssistant,
    entity_id: str,
    value: float,
    user: User,
) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": value},
        blocking=True,
        context=Context(user_id=user.id),
    )


async def _async_expect_refused(
    hass: HomeAssistant,
    entity_id: str,
    value: float,
    user: User,
) -> None:
    with pytest.raises(Unauthorized):
        await _async_set_share(hass, entity_id, value, user)
    await hass.async_block_till_done()


def _register_switch_services(hass: HomeAssistant) -> list[str]:
    turned_off: list[str] = []

    async def _turn_off(call: Any) -> None:
        raw = call.data.get("entity_id")
        entity_ids = raw if isinstance(raw, list) else [raw]
        for entity_id in entity_ids:
            turned_off.append(entity_id)
            hass.states.async_set(entity_id, "off")

    async def _turn_on(call: Any) -> None:
        raw = call.data.get("entity_id")
        entity_ids = raw if isinstance(raw, list) else [raw]
        for entity_id in entity_ids:
            hass.states.async_set(entity_id, "on")

    hass.services.async_register("switch", "turn_off", _turn_off)
    hass.services.async_register("switch", "turn_on", _turn_on)
    return turned_off


def _mark_owned_boiler(entry: MockConfigEntry) -> None:
    controller = entry.runtime_data.manager._active_load_controller
    assert controller is not None
    assert len(controller._loads) == 1
    load = controller._loads[0]
    load.owns_switch = True
    load.switch_is_on = True
    load.switch_available = True
    load.last_start_ts = dt_util.now() - timedelta(minutes=10)
    load.allocated_target_wh = 50.0
    controller._interval.interval_target_wh = 1234.0


def _boiler_snapshot(entry: MockConfigEntry) -> dict[str, Any]:
    controller = entry.runtime_data.manager._active_load_controller
    assert controller is not None
    return controller.get_snapshot()


async def _async_prepare_two_entries(
    hass: HomeAssistant,
) -> tuple[MockConfigEntry, MockConfigEntry, str, str, User, User, list[str]]:
    turned_off = _register_switch_services(hass)
    hass.states.async_set(BOILER_SWITCH, "on")
    hass.states.async_set(
        BOILER_POWER,
        "1500",
        attributes={"unit_of_measurement": "W", "device_class": "power"},
    )
    primary = _entry(
        receiver="sensor.receiver_import_total",
        shared="sensor.shared_energy_total",
        share=ORIGINAL_SHARE,
        with_load=True,
        title="Primary sharing",
    )
    other = _entry(
        receiver="sensor.other_receiver_import_total",
        shared="sensor.other_shared_energy_total",
        share=OTHER_SHARE,
        with_load=False,
        title="Other sharing",
    )
    await _async_setup_entry(
        hass,
        primary,
        receiver="sensor.receiver_import_total",
        shared="sensor.shared_energy_total",
    )
    await _async_setup_entry(
        hass,
        other,
        receiver="sensor.other_receiver_import_total",
        shared="sensor.other_shared_energy_total",
    )
    primary_number = _number_entity_id(hass, primary)
    other_number = _number_entity_id(hass, other)
    registry_entry = er.async_get(hass).async_get(primary_number)
    assert registry_entry is not None
    assert registry_entry.entity_category == EntityCategory.CONFIG
    owner, member = await _async_household_users(hass)
    _assert_controls(member, primary_number, allowed=True)
    _assert_controls(member, other_number, allowed=True)
    _mark_owned_boiler(primary)
    return (
        primary,
        other,
        primary_number,
        other_number,
        owner,
        member,
        turned_off,
    )


def _assert_shares(
    primary: MockConfigEntry,
    other: MockConfigEntry,
    *,
    primary_share: float,
    other_share: float,
) -> None:
    assert primary.options[CONF_FIXED_ALLOCATION_PERCENTAGE] == pytest.approx(
        primary_share
    )
    assert other.options[CONF_FIXED_ALLOCATION_PERCENTAGE] == pytest.approx(
        other_share
    )
    assert primary.runtime_data.manager.fixed_allocation_percentage == pytest.approx(
        primary_share
    )
    assert other.runtime_data.manager.fixed_allocation_percentage == pytest.approx(
        other_share
    )


def _assert_boiler_still_owned(entry: MockConfigEntry, turned_off: list[str]) -> None:
    snapshot = _boiler_snapshot(entry)
    assert snapshot["target_wh"] == pytest.approx(1234.0)
    assert snapshot["loads"][0]["allocated_target_wh"] == pytest.approx(50.0)
    assert snapshot["loads"][0]["owns_switch"] is True
    assert snapshot["loads"][0]["switch_is_on"] is True
    assert snapshot["loads"][0]["skip_reason"] != "allocation_paused"
    assert turned_off == []
    assert entry.runtime_data.manager.sharing_paused is False


async def test_non_admin_cannot_zero_share_or_release_owned_switches(
    hass: HomeAssistant,
) -> None:
    """A household user must not pause sharing or open an owned contactor."""
    primary, other, primary_number, other_number, owner, member, turned_off = (
        await _async_prepare_two_entries(hass)
    )

    await _async_set_share(hass, primary_number, 7.5, owner)
    await hass.async_block_till_done()
    _assert_shares(primary, other, primary_share=7.5, other_share=OTHER_SHARE)
    _mark_owned_boiler(primary)
    _assert_boiler_still_owned(primary, turned_off)

    await _async_expect_refused(hass, primary_number, 0, member)

    _assert_shares(primary, other, primary_share=7.5, other_share=OTHER_SHARE)
    state = hass.states.get(primary_number)
    assert state is not None
    assert float(state.state) == pytest.approx(7.5)
    assert hass.states.get(BOILER_SWITCH).state == "on"  # type: ignore[union-attr]
    _assert_boiler_still_owned(primary, turned_off)
    _assert_controls(member, other_number, allowed=True)


async def test_non_admin_cannot_persist_a_new_share_for_the_next_interval(
    hass: HomeAssistant,
) -> None:
    """A refused edit must leave the share the next settlement interval records."""
    primary, other, primary_number, _other_number, _owner, member, _turned_off = (
        await _async_prepare_two_entries(hass)
    )

    await _async_expect_refused(hass, primary_number, 42.5, member)
    _assert_shares(
        primary, other, primary_share=ORIGINAL_SHARE, other_share=OTHER_SHARE
    )

    manager = primary.runtime_data.manager
    assert await manager.async_process_now() == "baseline_initialized"
    set_cumulative_sources(
        hass,
        receiver_import_total_entity="sensor.receiver_import_total",
        shared_energy_total_entity="sensor.shared_energy_total",
        receiver_total=101.0,
        shared_total=10.7,
    )
    assert await manager.async_process_now() == "processed"
    last = manager.data.last_interval
    assert last is not None
    assert last.fixed_allocation_percentage == pytest.approx(ORIGINAL_SHARE)
    assert manager.sharing_paused is False
    _assert_shares(
        primary, other, primary_share=ORIGINAL_SHARE, other_share=OTHER_SHARE
    )


async def test_non_admin_device_action_cannot_change_share(
    hass: HomeAssistant,
) -> None:
    """Number device actions call the same set_value service as the UI."""
    _primary, other, primary_number, _other_number, _owner, member, _turned_off = (
        await _async_prepare_two_entries(hass)
    )
    with pytest.raises(Unauthorized):
        await async_call_action_from_config(
            hass,
            {
                "type": "set_value",
                "domain": "number",
                "device_id": "primary-device",
                "entity_id": primary_number,
                "value": 0,
            },
            {},
            Context(user_id=member.id),
        )
    await hass.async_block_till_done()
    _assert_shares(
        _primary, other, primary_share=ORIGINAL_SHARE, other_share=OTHER_SHARE
    )
    assert _primary.runtime_data.manager.sharing_paused is False


async def test_control_of_the_other_share_does_not_authorize_this_one(
    hass: HomeAssistant,
) -> None:
    """Permission to control one number must not change the other entry."""
    primary, other, primary_number, other_number, _owner, member, _turned_off = (
        await _async_prepare_two_entries(hass)
    )
    limited = member.groups[0]
    member.groups = [
        type(limited)(
            name="Other share only",
            policy={
                CAT_ENTITIES: {
                    "entity_ids": {other_number: {POLICY_CONTROL: True}},
                }
            },
            id="other-share-only",
        )
    ]
    _assert_controls(member, primary_number, allowed=False)
    _assert_controls(member, other_number, allowed=True)

    await _async_expect_refused(hass, primary_number, 0, member)
    _assert_shares(
        primary, other, primary_share=ORIGINAL_SHARE, other_share=OTHER_SHARE
    )


async def test_second_user_lookup_does_not_authorize_the_write(
    hass: HomeAssistant,
) -> None:
    """Reject the caller even if a later lookup of that same id returns an admin.

    Home Assistant resolves the service user once before the entity handler.
    A fix that looks the caller up again inside the handler and trusts that
    later result must still refuse the household member.
    """
    primary, other, primary_number, _other_number, owner, member, _turned_off = (
        await _async_prepare_two_entries(hass)
    )
    real_get_user = hass.auth.async_get_user
    lookups_in_handler = {"count": 0}

    async def _get_user(user_id: str) -> User | None:
        user = await real_get_user(user_id)
        in_handler = any(
            frame.filename.endswith("custom_components/energy_sharing/number.py")
            for frame in traceback.extract_stack()
        )
        if not in_handler or user_id != member.id:
            return user
        lookups_in_handler["count"] += 1
        if lookups_in_handler["count"] == 1:
            return user
        return owner

    hass.auth.async_get_user = _get_user  # type: ignore[method-assign]
    try:
        await _async_expect_refused(hass, primary_number, 15, member)
    finally:
        hass.auth.async_get_user = real_get_user  # type: ignore[method-assign]

    _assert_shares(
        primary, other, primary_share=ORIGINAL_SHARE, other_share=OTHER_SHARE
    )
    state = hass.states.get(primary_number)
    assert state is not None
    assert float(state.state) == pytest.approx(ORIGINAL_SHARE)


async def test_admin_set_value_changes_only_the_targeted_entry(
    hass: HomeAssistant,
) -> None:
    """An administrator may change the share, and only on the entity they set."""
    primary, other, primary_number, other_number, owner, member, _turned_off = (
        await _async_prepare_two_entries(hass)
    )
    await _async_set_share(hass, primary_number, 11, owner)
    await hass.async_block_till_done()
    _assert_shares(primary, other, primary_share=11, other_share=OTHER_SHARE)

    state = hass.states.get(primary_number)
    other_state = hass.states.get(other_number)
    assert state is not None and other_state is not None
    assert float(state.state) == pytest.approx(11)
    assert float(other_state.state) == pytest.approx(OTHER_SHARE)
    assert member.is_admin is False
