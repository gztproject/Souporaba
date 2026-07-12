"""Helper utilities for Energy Sharing."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    ATTR_LAST_PERIOD,
    ATTR_LAST_RESET,
    SUPPORTED_ENERGY_UNITS,
)


def parse_finite_number(value: Any) -> float | None:
    """Parse a finite numeric value."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_non_negative_number(value: Any) -> float | None:
    """Parse a finite, non-negative numeric value."""
    number = parse_finite_number(value)
    if number is None or number < 0:
        return None
    return number


def parse_reset_timestamp(value: Any) -> datetime | None:
    """Parse a last_reset timestamp."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


def convert_energy_to_kwh(value: float, unit: str | None) -> float:
    """Convert an energy value to kWh."""
    if unit is None:
        raise ValueError("missing_unit")
    if unit not in SUPPORTED_ENERGY_UNITS:
        raise ValueError("unsupported_unit")
    return EnergyConverter.convert(value, unit, "kWh")


async def validate_utility_meter_entity(hass: HomeAssistant, entity_id: str) -> None:
    """Validate that an entity is a usable utility meter source."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        raise ValueError("entity_unavailable")

    if ATTR_LAST_PERIOD not in state.attributes:
        raise ValueError("missing_last_period")

    last_period = parse_non_negative_number(state.attributes.get(ATTR_LAST_PERIOD))
    if last_period is None:
        raise ValueError("invalid_last_period")

    unit = state.attributes.get("unit_of_measurement")
    if unit is None:
        raise ValueError("missing_unit")

    try:
        convert_energy_to_kwh(last_period, unit)
    except ValueError as err:
        raise ValueError(str(err)) from err


async def validate_percentage_entity(hass: HomeAssistant, entity_id: str) -> None:
    """Validate that an entity can provide a percentage."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        raise ValueError("entity_unavailable")

    value = parse_finite_number(state.state)
    if value is None:
        raise ValueError("invalid_percentage")


def read_utility_meter_last_period_kwh(state: State) -> float:
    """Read and convert the last_period attribute to kWh."""
    last_period = parse_non_negative_number(state.attributes.get(ATTR_LAST_PERIOD))
    if last_period is None:
        raise HomeAssistantError("invalid_last_period")

    unit = state.attributes.get("unit_of_measurement")
    try:
        return convert_energy_to_kwh(last_period, unit)
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err


def read_percentage(state: State) -> float:
    """Read a percentage value from an entity state."""
    value = parse_finite_number(state.state)
    if value is None:
        raise HomeAssistantError("invalid_percentage")
    return value


def floor_to_interval_boundary(
    moment: datetime, interval_minutes: int
) -> datetime:
    """Floor a timestamp to the nearest interval boundary."""
    local_moment = dt_util.as_local(moment)
    minute = (local_moment.minute // interval_minutes) * interval_minutes
    return local_moment.replace(minute=minute, second=0, microsecond=0)


def get_expected_interval_end(
    now: datetime, interval_minutes: int
) -> datetime:
    """Return the end timestamp of the latest completed interval."""
    return floor_to_interval_boundary(now, interval_minutes)


def interval_id_from_end(interval_end: datetime) -> str:
    """Create a stable interval identifier from the interval end."""
    return dt_util.as_local(interval_end).isoformat()


def parse_interval_id(interval_id: str) -> datetime:
    """Parse an interval identifier back to a datetime."""
    parsed = dt_util.parse_datetime(interval_id)
    if parsed is None:
        raise ValueError(f"invalid_interval_id: {interval_id}")
    return dt_util.as_local(parsed)


def interval_start_from_end(interval_end: datetime, interval_minutes: int) -> datetime:
    """Calculate interval start from its end."""
    return interval_end - timedelta(minutes=interval_minutes)


def count_missed_intervals(
    last_processed_id: str | None,
    current_interval_id: str,
    interval_minutes: int,
) -> int:
    """Count missed intervals between the last processed and current interval."""
    if last_processed_id is None:
        return 0

    last_end = parse_interval_id(last_processed_id)
    current_end = parse_interval_id(current_interval_id)
    delta_minutes = (current_end - last_end).total_seconds() / 60

    if delta_minutes <= interval_minutes:
        return 0

    return int(delta_minutes / interval_minutes) - 1


def resets_match(
    reset_a: datetime,
    reset_b: datetime,
    tolerance_seconds: int,
) -> bool:
    """Return True when two reset timestamps identify the same boundary."""
    delta = abs((reset_a - reset_b).total_seconds())
    return delta <= tolerance_seconds


def reset_matches_interval_end(
    reset_time: datetime,
    interval_end: datetime,
    tolerance_seconds: int,
) -> bool:
    """Return True when a reset timestamp matches the interval end."""
    delta = abs((dt_util.as_local(reset_time) - interval_end).total_seconds())
    return delta <= tolerance_seconds
