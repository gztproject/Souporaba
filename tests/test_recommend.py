"""Tests for next-month share recommendations."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from custom_components.energy_sharing.archive import (
    ArchiveInterval,
    ArchiveLoadSnapshot,
)
from custom_components.energy_sharing.const import CONF_MONTHLY_PRODUCTION_OCT
from custom_components.energy_sharing.recommend import (
    BUILTIN_SI_MONTHLY_PRODUCTION,
    recommend_next_month_share,
    resolve_production_curve,
    seasonal_scale,
)


def _row(
    end: datetime,
    *,
    export: float,
    imported: float,
    active: float = 0.0,
    idle: bool = False,
) -> ArchiveInterval:
    start = end - timedelta(minutes=15)
    loads = []
    if active or idle:
        loads.append(
            ArchiveLoadSnapshot(
                switch_entity_id="switch.boiler",
                energy_wh=active * 1000.0,
                target_wh=active * 1000.0,
                idle_latched=idle,
            )
        )
    return ArchiveInterval(
        interval_id=f"{start.isoformat()}|{end.isoformat()}",
        interval_start=start,
        interval_end=end,
        provider_export_kwh=export,
        receiver_import_kwh=imported,
        shared_energy_kwh=imported,
        unused_shared_kwh=0.0,
        used_shared_kwh=imported,
        fixed_allocation_percentage=7.0,
        active_load_kwh=active,
        mopped_wh=active * 1000.0 if active else None,
        loads=loads,
    )


def test_oct_to_nov_scale_increases_required_share() -> None:
    scale = seasonal_scale(BUILTIN_SI_MONTHLY_PRODUCTION, 10, 11)
    assert scale < 1.0
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    now = datetime(2026, 10, 10, 12, 0, tzinfo=tz)
    intervals = [
        _row(datetime(2026, 10, 2, 12, 15, tzinfo=tz), export=10.0, imported=0.7)
        for _hour in range(8)
    ]
    rec = recommend_next_month_share(intervals, now=now, target_month="2026-11")
    unscaled = recommend_next_month_share(
        intervals,
        now=now,
        target_month="2026-10",
    )
    assert rec.conservative_pct is not None
    assert unscaled.conservative_pct is not None
    assert rec.conservative_pct > unscaled.conservative_pct


def test_conservative_not_above_optimistic_and_idle_is_organic() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    now = datetime(2026, 10, 10, 12, 0, tzinfo=tz)
    intervals = [
        _row(
            datetime(2026, 10, 2, 12, 15, tzinfo=tz),
            export=10.0,
            imported=1.5,
            active=0.8,
            idle=True,
        ),
        _row(
            datetime(2026, 10, 2, 12, 30, tzinfo=tz),
            export=10.0,
            imported=0.6,
            active=0.0,
            idle=False,
        ),
    ]
    rec = recommend_next_month_share(intervals, now=now, target_month="2026-11")
    assert rec.conservative_pct is not None
    assert rec.optimistic_pct is not None
    assert rec.conservative_pct <= rec.optimistic_pct
    idle_only = recommend_next_month_share(
        [
            _row(
                datetime(2026, 10, 2, 12, 15, tzinfo=tz),
                export=10.0,
                imported=1.5,
                active=0.8,
                idle=True,
            )
        ],
        now=now,
        target_month="2026-11",
    )
    soaking = recommend_next_month_share(
        [
            _row(
                datetime(2026, 10, 2, 12, 15, tzinfo=tz),
                export=10.0,
                imported=1.5,
                active=0.8,
                idle=False,
            )
        ],
        now=now,
        target_month="2026-11",
    )
    assert idle_only.optimistic_pct is not None
    assert soaking.optimistic_pct is not None
    assert idle_only.optimistic_pct <= soaking.optimistic_pct


def test_deadline_passed_after_the_tenth() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    before = recommend_next_month_share(
        [],
        now=datetime(2026, 10, 10, 18, 0, tzinfo=tz),
    )
    after = recommend_next_month_share(
        [],
        now=datetime(2026, 10, 11, 8, 0, tzinfo=tz),
    )
    assert before.deadline_passed is False
    assert after.deadline_passed is True
    assert before.target_month == "2026-11"


def test_user_curve_overrides_builtin() -> None:
    curve, source = resolve_production_curve({CONF_MONTHLY_PRODUCTION_OCT: 20.0})
    assert source == "user"
    assert curve[10] == 20.0
    assert curve[11] == BUILTIN_SI_MONTHLY_PRODUCTION[11]


def test_percentile_fallback_when_any_share_wastes() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    now = datetime(2026, 10, 10, 12, 0, tzinfo=tz)
    intervals = [
        _row(datetime(2026, 10, 2, 12, 15, tzinfo=tz), export=10.0, imported=0.0)
        for _ in range(8)
    ]
    rec = recommend_next_month_share(intervals, now=now, target_month="2026-11")
    assert rec.fallback_used is True
    assert rec.conservative_pct is not None
