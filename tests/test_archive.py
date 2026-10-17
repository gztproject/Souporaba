"""Tests for the interval archive."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from custom_components.energy_sharing.archive import (
    ArchiveInterval,
    ArchiveLoadSnapshot,
    append_archive_interval,
    archive_interval_from_result,
    intervals_in_range,
    prune_archive_intervals,
)
from custom_components.energy_sharing.models import IntervalResult


def _interval(
    end: datetime,
    *,
    export: float = 1.0,
    imported: float = 0.2,
    interval_id: str | None = None,
) -> ArchiveInterval:
    start = end - timedelta(minutes=15)
    return ArchiveInterval(
        interval_id=interval_id or f"{start.isoformat()}|{end.isoformat()}",
        interval_start=start,
        interval_end=end,
        provider_export_kwh=export,
        receiver_import_kwh=imported,
        shared_energy_kwh=0.1,
        unused_shared_kwh=0.0,
        used_shared_kwh=0.1,
        fixed_allocation_percentage=7.0,
        active_load_kwh=0.0,
    )


def test_append_replaces_same_interval_id() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    end = datetime(2026, 10, 1, 12, 15, tzinfo=tz)
    first = _interval(end, export=1.0, interval_id="same")
    second = _interval(end, export=2.0, interval_id="same")
    rows = append_archive_interval([], first)
    rows = append_archive_interval(rows, second)
    assert len(rows) == 1
    assert rows[0].provider_export_kwh == 2.0


def test_prune_drops_rows_older_than_retention() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    newest = datetime(2026, 10, 1, 12, 0, tzinfo=tz)
    old = _interval(newest - timedelta(days=500))
    recent = _interval(newest)
    kept = prune_archive_intervals([old, recent], newest_end=newest, retention_days=427)
    assert [row.interval_id for row in kept] == [recent.interval_id]


def test_range_is_end_exclusive() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    start = datetime(2026, 9, 1, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 1, 0, 0, tzinfo=tz)
    inside = _interval(datetime(2026, 9, 30, 23, 45, tzinfo=tz))
    boundary = _interval(end)
    selected = intervals_in_range([inside, boundary], start, end)
    assert [row.interval_id for row in selected] == [inside.interval_id]


def test_archive_interval_from_result_includes_alc() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    start = datetime(2026, 9, 1, 12, 0, tzinfo=tz)
    end = start + timedelta(minutes=15)
    result = IntervalResult(
        interval_id="id-1",
        interval_start=start,
        interval_end=end,
        operating_mode="export_and_percentage",
        receiver_import_interval_kwh=0.4,
        shared_energy_interval_kwh=0.2,
        used_shared_kwh=0.2,
        unused_shared_kwh=0.0,
        billable_energy_kwh=0.2,
        provider_export_interval_kwh=2.0,
        provider_export_source_type="measured",
        expected_shared_kwh=0.14,
        fixed_allocation_percentage=7.0,
        effective_allocation_pct=10.0,
        required_share_pct=20.0,
        ideal_share_pct=20.0,
        active_load_interval_kwh=0.15,
        ideal_share_excluding_active_loads_pct=12.5,
        allocation_utilization_pct=100.0,
        consumption_coverage_pct=50.0,
        allocation_difference_kwh=0.06,
        allocation_difference_pct=40.0,
        reconciliation_status="matched",
        settlement_accumulated=True,
        processed_at=end,
    )
    row = archive_interval_from_result(
        result,
        alc_snapshot={
            "mopped_wh": 150.0,
            "loads": [
                {
                    "switch_entity_id": "switch.boiler",
                    "energy_wh": 150.0,
                    "target_wh": 160.0,
                    "idle_latched": True,
                }
            ],
        },
    )
    assert row.mopped_wh == 150.0
    assert row.loads == [
        ArchiveLoadSnapshot(
            switch_entity_id="switch.boiler",
            energy_wh=150.0,
            target_wh=160.0,
            idle_latched=True,
        )
    ]
    restored = ArchiveInterval.from_dict(row.to_dict())
    assert restored is not None
    assert restored.loads[0].idle_latched is True
