"""Helper utilities for Energy Sharing."""

from __future__ import annotations

import math
from dataclasses import dataclass
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


class IntervalSourceValidationError(ValueError):
    """Raised when an interval source fails validation."""

    def __init__(self, code: str) -> None:
        """Initialize with a validation error code."""
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class IntervalSourceReading:
    """Validated reading from one interval source."""

    entity_id: str
    last_period_kwh: float
    reset_utc: datetime
    unit: str


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
    parsed: datetime | None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


def normalize_reset_to_utc(reset: datetime) -> datetime:
    """Normalize a reset timestamp to timezone-aware UTC."""
    return dt_util.as_utc(reset)


def convert_energy_to_kwh(value: float, unit: str | None) -> float:
    """Convert an energy value to kWh."""
    if unit is None:
        raise IntervalSourceValidationError("unsupported_energy_unit")
    if unit not in SUPPORTED_ENERGY_UNITS:
        raise IntervalSourceValidationError("unsupported_energy_unit")
    return EnergyConverter.convert(value, unit, "kWh")


def read_interval_source(state: State) -> IntervalSourceReading:
    """Read and validate one interval source state."""
    if state.state in ("unknown", "unavailable"):
        raise IntervalSourceValidationError("source_unavailable")

    if ATTR_LAST_PERIOD not in state.attributes:
        raise IntervalSourceValidationError("last_period_missing")

    last_period = parse_non_negative_number(state.attributes.get(ATTR_LAST_PERIOD))
    if last_period is None:
        raise IntervalSourceValidationError("invalid_interval_value")

    if ATTR_LAST_RESET not in state.attributes:
        raise IntervalSourceValidationError("last_reset_missing")

    reset = parse_reset_timestamp(state.attributes.get(ATTR_LAST_RESET))
    if reset is None:
        raise IntervalSourceValidationError("last_reset_missing")

    unit = state.attributes.get("unit_of_measurement")
    try:
        last_period_kwh = convert_energy_to_kwh(last_period, unit)
    except IntervalSourceValidationError:
        raise
    except ValueError as err:
        raise IntervalSourceValidationError("unsupported_energy_unit") from err

    return IntervalSourceReading(
        entity_id=state.entity_id,
        last_period_kwh=last_period_kwh,
        reset_utc=normalize_reset_to_utc(reset),
        unit=str(unit),
    )


async def validate_interval_source(hass: HomeAssistant, entity_id: str) -> None:
    """Validate that an entity is a usable interval source."""
    state = hass.states.get(entity_id)
    if state is None:
        raise IntervalSourceValidationError("source_missing")
    try:
        read_interval_source(state)
    except IntervalSourceValidationError:
        raise


async def validate_percentage_source(hass: HomeAssistant, entity_id: str) -> None:
    """Validate that an entity can provide a percentage."""
    state = hass.states.get(entity_id)
    if state is None:
        raise IntervalSourceValidationError("percentage_invalid")
    if state.state in ("unknown", "unavailable"):
        raise IntervalSourceValidationError("percentage_invalid")
    if parse_finite_number(state.state) is None:
        raise IntervalSourceValidationError("percentage_invalid")


def read_percentage(state: State) -> float:
    """Read a percentage value from an entity state."""
    value = parse_finite_number(state.state)
    if value is None:
        raise HomeAssistantError("invalid_percentage")
    return value


def floor_to_interval_boundary(moment: datetime, interval_minutes: int) -> datetime:
    """Floor a timestamp to the nearest interval boundary in local time."""
    local_moment = dt_util.as_local(moment)
    minute = (local_moment.minute // interval_minutes) * interval_minutes
    return local_moment.replace(minute=minute, second=0, microsecond=0)


def get_expected_interval_end(now: datetime, interval_minutes: int) -> datetime:
    """Return the end timestamp of the latest completed interval."""
    return floor_to_interval_boundary(now, interval_minutes)


def interval_id_from_reset(reset_utc: datetime) -> str:
    """Create a stable interval identifier from a normalized UTC reset."""
    return normalize_reset_to_utc(reset_utc).isoformat()


def parse_interval_id(interval_id: str) -> datetime:
    """Parse an interval identifier back to a UTC datetime."""
    parsed = dt_util.parse_datetime(interval_id)
    if parsed is None:
        raise ValueError(f"invalid_interval_id: {interval_id}")
    return normalize_reset_to_utc(parsed)


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


def resets_match_utc(
    reset_a: datetime,
    reset_b: datetime,
    tolerance_seconds: int,
) -> bool:
    """Return True when two UTC reset timestamps identify the same boundary."""
    utc_a = normalize_reset_to_utc(reset_a)
    utc_b = normalize_reset_to_utc(reset_b)
    delta = abs((utc_a - utc_b).total_seconds())
    return delta <= tolerance_seconds


def reset_matches_interval_end(
    reset_utc: datetime,
    interval_end_local: datetime,
    tolerance_seconds: int,
) -> bool:
    """Return True when a UTC reset matches the expected local interval end."""
    reset_local = dt_util.as_local(normalize_reset_to_utc(reset_utc))
    delta = abs((reset_local - interval_end_local).total_seconds())
    return delta <= tolerance_seconds


def validate_sources_synchronized(
    readings: list[IntervalSourceReading],
    tolerance_seconds: int,
) -> datetime:
    """Validate that all readings share the same interval reset boundary."""
    if not readings:
        raise IntervalSourceValidationError("source_missing")

    reference = readings[0].reset_utc
    for reading in readings[1:]:
        if not resets_match_utc(reference, reading.reset_utc, tolerance_seconds):
            raise IntervalSourceValidationError("source_intervals_unsynchronized")

    return reference
