"""Tests for helper utilities."""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.energy_sharing.helpers import (
    CumulativeSourceReading,
    SourceValidationError,
    convert_energy_to_kwh,
    interval_id_from_boundaries,
    read_cumulative_source,
    source_is_fresh_enough,
)


def test_convert_wh_to_kwh() -> None:
    assert convert_energy_to_kwh(1500.0, "Wh") == pytest.approx(1.5)


def test_convert_unsupported_unit() -> None:
    with pytest.raises(SourceValidationError, match="unsupported_energy_unit"):
        convert_energy_to_kwh(1.0, "bananas")


def test_read_cumulative_source() -> None:
    state = State(
        "sensor.test",
        "123.45",
        {"unit_of_measurement": "kWh"},
    )
    reading = read_cumulative_source(state)
    assert reading.total_kwh == pytest.approx(123.45)


def test_read_cumulative_source_rejects_negative() -> None:
    state = State("sensor.test", "-1", {"unit_of_measurement": "kWh"})
    with pytest.raises(SourceValidationError, match="source_not_numeric"):
        read_cumulative_source(state)


def test_interval_id_from_boundaries() -> None:
    start = datetime(
        2026, 7, 12, 14, 45, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    end = datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    interval_id = interval_id_from_boundaries(start, end)
    assert "|" in interval_id


def test_source_freshness_without_timestamp() -> None:
    reading = CumulativeSourceReading(
        entity_id="sensor.test",
        total_kwh=1.0,
        unit="kWh",
    )
    boundary = datetime(
        2026, 7, 12, 15, 0, 0, tzinfo=dt_util.get_time_zone("Europe/Ljubljana")
    )
    assert source_is_fresh_enough(reading, boundary, 300) is True
