"""Helper utilities for Energy Sharing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .const import SUPPORTED_ENERGY_UNITS


class SourceValidationError(ValueError):
    """Raised when a cumulative source fails validation."""

    def __init__(self, code: str) -> None:
        """Initialize with a validation error code."""
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class CumulativeSourceReading:
    """Validated reading from one cumulative energy source."""

    entity_id: str
    total_kwh: float
    unit: str
    measurement_timestamp: datetime | None = None
    state_last_updated: datetime | None = None


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


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp from a state attribute or ISO string."""
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
    return dt_util.as_utc(parsed)


def convert_energy_to_kwh(value: float, unit: str | None) -> float:
    """Convert an energy value to kWh."""
    if unit is None:
        raise SourceValidationError("unsupported_energy_unit")
    if unit not in SUPPORTED_ENERGY_UNITS:
        raise SourceValidationError("unsupported_energy_unit")
    return EnergyConverter.convert(value, unit, "kWh")


def read_cumulative_source(
    state: State,
    timestamp_attr: str | None = None,
) -> CumulativeSourceReading:
    """Read and validate one cumulative energy source state."""
    if state.state in ("unknown", "unavailable"):
        raise SourceValidationError("source_unavailable")

    total = parse_non_negative_number(state.state)
    if total is None:
        raise SourceValidationError("source_not_numeric")

    unit = state.attributes.get("unit_of_measurement")
    try:
        total_kwh = convert_energy_to_kwh(total, unit)
    except SourceValidationError:
        raise
    except ValueError as err:
        raise SourceValidationError("unsupported_energy_unit") from err

    measurement_timestamp: datetime | None = None
    if timestamp_attr:
        measurement_timestamp = parse_timestamp(
            state.attributes.get(timestamp_attr)
        )

    state_last_updated = None
    if state.last_updated:
        state_last_updated = dt_util.as_utc(state.last_updated)

    return CumulativeSourceReading(
        entity_id=state.entity_id,
        total_kwh=total_kwh,
        unit=str(unit),
        measurement_timestamp=measurement_timestamp,
        state_last_updated=state_last_updated,
    )


async def validate_cumulative_source(hass: HomeAssistant, entity_id: str) -> None:
    """Validate that an entity is a usable cumulative energy source."""
    state = hass.states.get(entity_id)
    if state is None:
        raise SourceValidationError("source_missing")
    read_cumulative_source(state)


def floor_to_interval_boundary(moment: datetime, interval_minutes: int) -> datetime:
    """Floor a timestamp to the nearest interval boundary in local time."""
    local_moment = dt_util.as_local(moment)
    minute = (local_moment.minute // interval_minutes) * interval_minutes
    return local_moment.replace(minute=minute, second=0, microsecond=0)


def get_completed_interval(
    now: datetime, interval_minutes: int
) -> tuple[datetime, datetime]:
    """Return start and end of the latest completed interval in local time."""
    interval_end = floor_to_interval_boundary(now, interval_minutes)
    interval_start = interval_end - timedelta(minutes=interval_minutes)
    return interval_start, interval_end


def interval_id_from_boundaries(
    interval_start: datetime, interval_end: datetime
) -> str:
    """Create a stable interval identifier from UTC-normalized boundaries."""
    start_utc = dt_util.as_utc(interval_start).isoformat()
    end_utc = dt_util.as_utc(interval_end).isoformat()
    return f"{start_utc}|{end_utc}"


def parse_interval_id(interval_id: str) -> tuple[datetime, datetime]:
    """Parse an interval identifier back to UTC start and end datetimes."""
    if "|" not in interval_id:
        raise ValueError(f"invalid_interval_id: {interval_id}")
    start_raw, end_raw = interval_id.split("|", 1)
    start = dt_util.parse_datetime(start_raw)
    end = dt_util.parse_datetime(end_raw)
    if start is None or end is None:
        raise ValueError(f"invalid_interval_id: {interval_id}")
    return dt_util.as_utc(start), dt_util.as_utc(end)


def count_missed_intervals(
    last_processed_id: str | None,
    current_interval_id: str,
    interval_minutes: int,
) -> int:
    """Count missed intervals between the last processed and current interval."""
    if last_processed_id is None:
        return 0

    _, last_end = parse_interval_id(last_processed_id)
    _, current_end = parse_interval_id(current_interval_id)
    delta_minutes = (current_end - last_end).total_seconds() / 60

    if delta_minutes <= interval_minutes:
        return 0

    return int(delta_minutes / interval_minutes) - 1


def source_is_fresh_enough(
    reading: CumulativeSourceReading,
    boundary_end: datetime,
    freshness_tolerance_seconds: int,
) -> bool:
    """Return True when a source plausibly reflects the completed interval."""
    reference = reading.measurement_timestamp or reading.state_last_updated
    if reference is None:
        return True

    boundary_utc = dt_util.as_utc(boundary_end)
    reference_utc = dt_util.as_utc(reference)
    if reference_utc < boundary_utc - timedelta(seconds=freshness_tolerance_seconds):
        return False
    return reference_utc <= boundary_utc + timedelta(
        seconds=freshness_tolerance_seconds
    )
