"""Non-finite settlement results must not wedge later intervals.

A fixed allocation percentage inside the number entity's 0–100 range, and a
finite subnormal step on a cumulative energy sensor, can make a settlement
division overflow. The in-memory totals keep that non-finite value. The next
processing pass publishes entity state before it settles the new interval, and
Home Assistant rejects the non-finite sensor state, so later intervals are never
recorded until the integration is reloaded.

These tests fail while that happens. They pass when an accepted percentage or
sensor step leaves only finite figures and the following interval is stored
without reloading the config entry.
"""

from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import Any

import pytest
import voluptuous as vol
from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import InvalidData
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.const import (
    ARCHIVE_STORAGE_KEY,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    DOMAIN,
    STORAGE_KEY,
)
from custom_components.energy_sharing.helpers import (
    get_completed_interval,
    interval_id_from_boundaries,
)
from custom_components.energy_sharing.manager import EnergySharingManager
from tests.conftest import set_cumulative_sources

# Positive, finite, and inside the advertised 0–100 limits. Dividing a normal
# interval by this fraction overflows.
_TINY_SHARE_PCT = 1e-310
_SUBNORMAL_KWH = 1e-310
_NORMAL_SHARE_PCT = 7.0


@pytest.fixture(autouse=True)
def _scrub_nonfinite_before_shutdown(hass: HomeAssistant):
    """Let Home Assistant stop even when a test leaves a non-finite sensor."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        _replace_nonfinite(runtime.manager.data)
        _replace_nonfinite(runtime.manager.archive.intervals)
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        runtime.manager.data.last_interval = None
        for name in (
            "cumulative_provider_export",
            "cumulative_expected_shared",
            "cumulative_receiver_import",
            "cumulative_shared_energy",
            "cumulative_used",
            "cumulative_unused",
            "cumulative_billable_energy",
        ):
            setattr(runtime.manager.data, name, 0.0)
    components = hass.data.get("entity_components", {})
    for component in components.values():
        for platform in getattr(component, "_platforms", {}).values():
            platform.async_unsub_polling()
        for entity in list(component.entities):
            entity._attr_should_poll = False
            entity.__dict__.pop("should_poll", None)
            entity._attr_native_value = None
            entity.__dict__["native_value"] = None


def _replace_nonfinite(value: Any) -> Any:
    """Replace non-finite floats so shutdown can publish entity state."""
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if isinstance(value, dict):
        for key, item in list(value.items()):
            value[key] = _replace_nonfinite(item)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _replace_nonfinite(item)
        return value
    if is_dataclass(value):
        for field in fields(value):
            current = getattr(value, field.name)
            replaced = _replace_nonfinite(current)
            if replaced is not current:
                setattr(value, field.name, replaced)
        return value
    return value


def _nonfinite_paths(value: Any, path: str = "$") -> list[str]:
    if isinstance(value, float):
        if not math.isfinite(value):
            return [path]
        return []
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            found.extend(_nonfinite_paths(item, f"{path}.{key}"))
        return found
    if isinstance(value, list):
        found = []
        for index, item in enumerate(value):
            found.extend(_nonfinite_paths(item, f"{path}[{index}]"))
        return found
    if is_dataclass(value):
        found = []
        for field in fields(value):
            found.extend(
                _nonfinite_paths(getattr(value, field.name), f"{path}.{field.name}")
            )
        return found
    return []


def _assert_runtime_finite(manager: EnergySharingManager) -> None:
    paths = _nonfinite_paths(manager.data)
    paths.extend(_nonfinite_paths(manager.archive.intervals, "$archive"))
    assert paths == [], paths


def _local(hour: int, minute: int, second: int = 10) -> datetime:
    return datetime(
        2026,
        7,
        12,
        hour,
        minute,
        second,
        tzinfo=dt_util.get_time_zone("Europe/Ljubljana"),
    )


def _completed_interval_id(moment: datetime, interval_minutes: int = 15) -> str:
    start, end = get_completed_interval(moment, interval_minutes)
    return interval_id_from_boundaries(start, end)


async def _settle(manager: EnergySharingManager) -> str:
    """Run one settlement pass. A non-finite sensor state fails the test."""
    try:
        return await manager.async_process_now()
    except ValueError as err:
        # Drain update tasks created by the options listener so their sensor
        # error is observed here instead of as an unretrieved task at shutdown.
        with suppress(ValueError):
            await manager.hass.async_block_till_done()
        pytest.fail(f"settlement published a non-finite sensor state: {err}")


async def _percentage_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_fixed_allocation_percentage"
    )
    assert entity_id is not None
    return entity_id


async def _try_set_percentage_number(
    hass: HomeAssistant, entry: MockConfigEntry, value: float
) -> bool:
    """Return False when the number entity rejects the value."""
    entity_id = await _percentage_entity_id(hass, entry)
    try:
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": value},
            blocking=True,
        )
    except ServiceValidationError:
        return False
    await hass.async_block_till_done()
    return True


async def _try_set_percentage_options(
    hass: HomeAssistant, entry: MockConfigEntry, value: float
) -> bool:
    """Return False when the options flow rejects the value."""
    try:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "name": "Energy Sharing",
                CONF_FIXED_ALLOCATION_PERCENTAGE: value,
            },
        )
    except (InvalidData, vol.Invalid):
        return False
    await hass.async_block_till_done()
    if result.get("errors"):
        return False
    return result["type"] == "create_entry"


def _stop_sensor_polling(hass: HomeAssistant) -> None:
    """Polling after a clock jump republishes the bad sensor state in a side task."""
    components = hass.data.get("entity_components", {})
    for component in components.values():
        for platform in getattr(component, "_platforms", {}).values():
            platform.async_unsub_polling()
        for entity in list(component.entities):
            entity._attr_should_poll = False
            entity.__dict__.pop("should_poll", None)


def _publish(
    hass: HomeAssistant,
    receiver_entity: str,
    shared_entity: str,
    provider_entity: str | None,
    totals: tuple[float, float, float | None],
) -> None:
    receiver_total, shared_total, provider_total = totals
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver_entity,
        shared_energy_total_entity=shared_entity,
        receiver_total=receiver_total,
        shared_total=shared_total,
        provider_export_total_entity=provider_entity,
        provider_total=provider_total,
    )


def _assert_recovery_stored(
    hass_storage: dict[str, Any],
    entry: MockConfigEntry,
    recovery_id: str,
) -> None:
    """The follow-up interval must be in the serialized stores, still finite."""
    archive = hass_storage[f"{ARCHIVE_STORAGE_KEY}.{entry.entry_id}"]
    stored = hass_storage[f"{STORAGE_KEY}.{entry.entry_id}"]
    assert _nonfinite_paths(archive) == []
    assert _nonfinite_paths(stored) == []

    intervals = archive["data"]["intervals"]
    match = next(
        (row for row in intervals if row.get("interval_id") == recovery_id),
        None,
    )
    assert match is not None
    export = match["provider_export_kwh"]
    assert isinstance(export, (int, float))
    assert math.isfinite(float(export))
    assert float(export) > 0

    assert stored["data"]["last_processed_interval_id"] == recovery_id
    cumulative = stored["data"]["cumulative_provider_export"]
    assert isinstance(cumulative, (int, float))
    assert math.isfinite(float(cumulative))
    assert float(cumulative) > 0


async def _run_percentage_overflow(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    entry: MockConfigEntry,
    *,
    receiver_entity: str,
    shared_entity: str,
    provider_entity: str | None,
    set_percentage,
) -> None:
    manager: EnergySharingManager = entry.runtime_data.manager
    _stop_sensor_polling(hass)
    provider_total = 200.0 if provider_entity else None
    _publish(
        hass,
        receiver_entity,
        shared_entity,
        provider_entity,
        (100.0, 10.0, provider_total),
    )
    assert await _settle(manager) == "baseline_initialized"

    accepted = await set_percentage(hass, entry, _TINY_SHARE_PCT)
    if accepted:
        stored_pct = float(entry.options[CONF_FIXED_ALLOCATION_PERCENTAGE])
        assert 0.0 <= stored_pct <= 100.0

    with freeze_time(_local(15, 15)):
        _publish(
            hass,
            receiver_entity,
            shared_entity,
            provider_entity,
            (101.0, 10.7, 210.0 if provider_entity else None),
        )
        assert await _settle(manager) == "processed"
        _assert_runtime_finite(manager)

    assert await _try_set_percentage_number(hass, entry, _NORMAL_SHARE_PCT)
    assert entry.options[CONF_FIXED_ALLOCATION_PERCENTAGE] == pytest.approx(
        _NORMAL_SHARE_PCT
    )

    recovery_at = _local(15, 30)
    with freeze_time(recovery_at):
        _publish(
            hass,
            receiver_entity,
            shared_entity,
            provider_entity,
            (102.0, 11.4, 220.0 if provider_entity else None),
        )
        assert await _settle(manager) == "processed"
        recovery_id = _completed_interval_id(recovery_at)
        _assert_runtime_finite(manager)
        _assert_recovery_stored(hass_storage, entry, recovery_id)
        last = manager.data.last_interval
        assert last is not None
        assert last.interval_id == recovery_id
        assert last.provider_export_interval_kwh is not None
        assert math.isfinite(last.provider_export_interval_kwh)


async def _rebase_then_step(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    entry: MockConfigEntry,
    *,
    receiver_entity: str,
    shared_entity: str,
    provider_entity: str | None,
    baseline: tuple[float, float, float | None],
    reset_to: tuple[float, float, float | None],
    step_to: tuple[float, float, float | None],
    follow_to: tuple[float, float, float | None],
) -> None:
    """Rebase a counter through zero, then take a subnormal step."""
    manager: EnergySharingManager = entry.runtime_data.manager
    _stop_sensor_polling(hass)
    _publish(hass, receiver_entity, shared_entity, provider_entity, baseline)
    assert await _settle(manager) == "baseline_initialized"

    with freeze_time(_local(15, 15)):
        _publish(hass, receiver_entity, shared_entity, provider_entity, reset_to)
        pending = await _settle(manager)
        assert pending.startswith("retrying:counter_reset:")

    with freeze_time(_local(15, 16, 20)):
        committed = await _settle(manager)
        assert committed.startswith("skipped:counter_reset:")

    with freeze_time(_local(15, 30)):
        _publish(hass, receiver_entity, shared_entity, provider_entity, step_to)
        assert await _settle(manager) == "processed"
        _assert_runtime_finite(manager)

    recovery_at = _local(15, 45)
    with freeze_time(recovery_at):
        _publish(hass, receiver_entity, shared_entity, provider_entity, follow_to)
        assert await _settle(manager) == "processed"
        recovery_id = _completed_interval_id(recovery_at)
        _assert_runtime_finite(manager)
        _assert_recovery_stored(hass_storage, entry, recovery_id)


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_number_set_value_tiny_share_percentage_only(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    """number.set_value(1e-310) must not infer an infinite provider export."""
    await _run_percentage_overflow(
        hass,
        hass_storage,
        setup_percentage_only,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=None,
        set_percentage=_try_set_percentage_number,
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_number_set_value_tiny_share_export_and_percentage(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    """The same number value must not overflow the allocation-difference percentage."""
    await _run_percentage_overflow(
        hass,
        hass_storage,
        setup_export_and_percentage,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=provider_export_total_entity,
        set_percentage=_try_set_percentage_number,
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_options_flow_tiny_share_percentage_only(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    """The options flow writes the same percentage the number entity writes."""
    await _run_percentage_overflow(
        hass,
        hass_storage,
        setup_percentage_only,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=None,
        set_percentage=_try_set_percentage_options,
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_options_flow_tiny_share_export_and_percentage(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    """Export-and-percentage options must reject or safely settle a tiny share."""
    await _run_percentage_overflow(
        hass,
        hass_storage,
        setup_export_and_percentage,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=provider_export_total_entity,
        set_percentage=_try_set_percentage_options,
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_user_flow_tiny_share_does_not_wedge(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    """Initial setup with a tiny contractual share must not wedge settlement."""
    _publish(
        hass,
        receiver_import_total_entity,
        shared_energy_total_entity,
        None,
        (100.0, 10.0, None),
    )
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "name": "Energy Sharing",
                "receiver_import_total_source": receiver_import_total_entity,
                "shared_energy_total_source": shared_energy_total_entity,
                CONF_FIXED_ALLOCATION_PERCENTAGE: _TINY_SHARE_PCT,
            },
        )
    except (InvalidData, vol.Invalid):
        return

    if result["type"] != "create_entry":
        assert result.get("errors")
        return

    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    if entry.state is not ConfigEntryState.LOADED:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    manager = entry.runtime_data.manager
    _stop_sensor_polling(hass)
    stored_pct = float(entry.options[CONF_FIXED_ALLOCATION_PERCENTAGE])
    assert 0.0 <= stored_pct <= 100.0

    assert await _settle(manager) == "baseline_initialized"
    with freeze_time(_local(15, 15)):
        _publish(
            hass,
            receiver_import_total_entity,
            shared_energy_total_entity,
            None,
            (101.0, 10.7, None),
        )
        assert await _settle(manager) == "processed"
        _assert_runtime_finite(manager)

    assert await _try_set_percentage_number(hass, entry, _NORMAL_SHARE_PCT)
    recovery_at = _local(15, 30)
    with freeze_time(recovery_at):
        _publish(
            hass,
            receiver_import_total_entity,
            shared_energy_total_entity,
            None,
            (102.0, 11.4, None),
        )
        assert await _settle(manager) == "processed"
        _assert_runtime_finite(manager)
        _assert_recovery_stored(
            hass_storage, entry, _completed_interval_id(recovery_at)
        )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_subnormal_shared_step_percentage_only(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_percentage_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
) -> None:
    """A near-zero shared step against a normal import must stay finite.

    The contractual share stays at 7%. The shared counter is rebased to zero
    and the next interval moves it by a subnormal amount while import moves by
    1 kWh, which overflows required share today.
    """
    await _rebase_then_step(
        hass,
        hass_storage,
        setup_percentage_only,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=None,
        baseline=(100.0, 10.0, None),
        reset_to=(101.0, 0.0, None),
        step_to=(102.0, _SUBNORMAL_KWH, None),
        follow_to=(103.0, _SUBNORMAL_KWH + 0.7, None),
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_subnormal_provider_step_export_only(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry_export_only: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    """Export-only allocation percentages must stay finite for a tiny export step."""
    entry = mock_config_entry_export_only
    entry.add_to_hass(hass)
    _publish(
        hass,
        receiver_import_total_entity,
        shared_energy_total_entity,
        provider_export_total_entity,
        (100.0, 10.0, 200.0),
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _rebase_then_step(
        hass,
        hass_storage,
        entry,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=provider_export_total_entity,
        baseline=(100.0, 10.0, 200.0),
        reset_to=(101.0, 10.7, 0.0),
        step_to=(102.0, 11.4, _SUBNORMAL_KWH),
        follow_to=(103.0, 12.1, _SUBNORMAL_KWH + 10.0),
    )


@freeze_time("2026-07-12 15:00:10+02:00")
async def test_subnormal_provider_step_export_and_percentage(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_export_and_percentage: MockConfigEntry,
    receiver_import_total_entity: str,
    shared_energy_total_entity: str,
    provider_export_total_entity: str,
) -> None:
    """A tiny measured export must not overflow allocation difference or share."""
    await _rebase_then_step(
        hass,
        hass_storage,
        setup_export_and_percentage,
        receiver_entity=receiver_import_total_entity,
        shared_entity=shared_energy_total_entity,
        provider_entity=provider_export_total_entity,
        baseline=(100.0, 10.0, 200.0),
        reset_to=(101.0, 10.7, 0.0),
        step_to=(102.0, 11.4, _SUBNORMAL_KWH),
        follow_to=(103.0, 12.1, _SUBNORMAL_KWH + 10.0),
    )
