"""Next-month conservative and optimistic share recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .archive import ArchiveInterval
from .const import (
    MAX_ALLOCATION_PERCENTAGE,
    MIN_ALLOCATION_PERCENTAGE,
    MOJ_ELEKTRO_DEADLINE_DAY,
    MONTHLY_PRODUCTION_OPTION_KEYS,
    RECOMMEND_MIN_DAYLIGHT_INTERVALS,
    RECOMMEND_ROUND_DECIMALS,
    RECOMMEND_UNUSED_RATIO_CONSERVATIVE,
    RECOMMEND_UNUSED_RATIO_OPTIMISTIC,
)
from .models import clamp

# Mid-Slovenia relative monthly PV yield (% of annual). PVGIS-style factors
# for a typical south-facing rooftop around Ljubljana; only month-to-month
# ratios are used when scaling measured Oddajnik export.
BUILTIN_SI_MONTHLY_PRODUCTION: dict[int, float] = {
    1: 3.2,
    2: 5.5,
    3: 8.9,
    4: 11.4,
    5: 13.1,
    6: 13.4,
    7: 13.6,
    8: 12.1,
    9: 8.8,
    10: 5.7,
    11: 2.8,
    12: 1.5,
}

PRODUCTION_CURVE_BUILTIN = "builtin_si"
PRODUCTION_CURVE_USER = "user"


@dataclass(slots=True)
class ShareRecommendation:
    """Recommended contractual share for the next Moj Elektro month."""

    target_month: str
    deadline_date: str
    deadline_passed: bool
    reference_month: str
    seasonal_scale: float
    observation_start: str
    observation_end: str
    daylight_intervals: int
    conservative_pct: float | None
    optimistic_pct: float | None
    conservative_unused_kwh: float | None
    conservative_coverage_pct: float | None
    optimistic_unused_kwh: float | None
    optimistic_coverage_pct: float | None
    production_curve_source: str
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_month": self.target_month,
            "deadline_date": self.deadline_date,
            "deadline_passed": self.deadline_passed,
            "reference_month": self.reference_month,
            "seasonal_scale": self.seasonal_scale,
            "observation_start": self.observation_start,
            "observation_end": self.observation_end,
            "daylight_intervals": self.daylight_intervals,
            "conservative_pct": self.conservative_pct,
            "optimistic_pct": self.optimistic_pct,
            "conservative_unused_kwh": self.conservative_unused_kwh,
            "conservative_coverage_pct": self.conservative_coverage_pct,
            "optimistic_unused_kwh": self.optimistic_unused_kwh,
            "optimistic_coverage_pct": self.optimistic_coverage_pct,
            "production_curve_source": self.production_curve_source,
            "fallback_used": self.fallback_used,
        }


def as_aware_local(value: datetime) -> datetime:
    """Keep an aware datetime; localize naive values with HA's timezone."""
    if value.tzinfo is not None:
        return value
    return dt_util.as_local(value)


def start_of_month(value: datetime) -> datetime:
    """Return local midnight on the first day of value's month."""
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(value: datetime, months: int) -> datetime:
    """Shift a datetime by a whole number of calendar months."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=1)


def observation_window(now: datetime) -> tuple[datetime, datetime]:
    """Return [start of previous month, now] for recommendation samples."""
    local = as_aware_local(now)
    start = start_of_month(add_months(start_of_month(local), -1))
    return start, local


def format_year_month(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def parse_year_month(value: str | None, default: datetime) -> datetime:
    """Parse YYYY-MM into the first of that month, or use default."""
    if not value:
        return start_of_month(default)
    try:
        year_str, month_str = value.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        if month < 1 or month > 12:
            return start_of_month(default)
        return default.replace(
            year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    except (TypeError, ValueError):
        return start_of_month(default)


def resolve_production_curve(
    options: dict[str, Any] | None,
) -> tuple[dict[int, float], str]:
    """Return monthly factors and whether they came from user options."""
    curve = dict(BUILTIN_SI_MONTHLY_PRODUCTION)
    if not options:
        return curve, PRODUCTION_CURVE_BUILTIN
    used_user = False
    for month, key in MONTHLY_PRODUCTION_OPTION_KEYS.items():
        raw = options.get(key)
        if raw in (None, ""):
            stored = options.get("monthly_production")
            if isinstance(stored, dict):
                raw = stored.get(str(month), stored.get(month))
        if raw in (None, ""):
            continue
        try:
            factor = float(raw)
        except (TypeError, ValueError):
            continue
        if factor > 0:
            curve[month] = factor
            used_user = True
    source = PRODUCTION_CURVE_USER if used_user else PRODUCTION_CURVE_BUILTIN
    return curve, source


def seasonal_scale(
    curve: dict[int, float], reference_month: int, target_month: int
) -> float:
    """Scale measured export from the reference month into the target month."""
    reference = curve.get(reference_month, 0.0)
    target = curve.get(target_month, 0.0)
    if reference <= 0 or target <= 0:
        return 1.0
    return target / reference


def is_daylight(interval: ArchiveInterval) -> bool:
    export = interval.provider_export_kwh
    return export is not None and export > 0


def organic_load_kwh(interval: ArchiveInterval) -> float:
    return max(interval.receiver_import_kwh - interval.active_load_kwh, 0.0)


def optimistic_load_kwh(interval: ArchiveInterval) -> float:
    """Full import unless a tank was already full (idle latched)."""
    if any(load.idle_latched for load in interval.loads):
        return organic_load_kwh(interval)
    return max(interval.receiver_import_kwh, 0.0)


def _round_share(value: float) -> float:
    rounded = round(value, RECOMMEND_ROUND_DECIMALS)
    return clamp(rounded, MIN_ALLOCATION_PERCENTAGE, MAX_ALLOCATION_PERCENTAGE)


def simulate_share(
    intervals: list[ArchiveInterval],
    percentage: float,
    *,
    scale: float,
    load_fn: Any,
) -> tuple[float, float, float]:
    """Return unused_kwh, coverage_pct, unused_ratio for a candidate share."""
    unused = 0.0
    expected = 0.0
    covered = 0.0
    load_total = 0.0
    for interval in intervals:
        export = interval.provider_export_kwh
        if export is None or export <= 0:
            continue
        scaled_export = export * scale
        expected_shared = scaled_export * percentage / 100.0
        load = float(load_fn(interval))
        unused += max(0.0, expected_shared - load)
        covered += min(expected_shared, load)
        expected += expected_shared
        load_total += load
    unused_ratio = unused / expected if expected > 0 else 1.0
    coverage_pct = 100.0 * covered / load_total if load_total > 0 else 0.0
    return unused, coverage_pct, unused_ratio


def largest_share_within_unused_ratio(
    intervals: list[ArchiveInterval],
    *,
    scale: float,
    load_fn: Any,
    max_unused_ratio: float,
) -> float | None:
    """Binary-search the largest share whose unused/expected stays in budget."""
    low = MIN_ALLOCATION_PERCENTAGE
    high = MAX_ALLOCATION_PERCENTAGE
    best: float | None = None
    _unused, _coverage, low_ratio = simulate_share(
        intervals, low, scale=scale, load_fn=load_fn
    )
    if low_ratio > max_unused_ratio:
        return None
    best = low
    for _ in range(40):
        mid = (low + high) / 2.0
        _unused, _coverage, ratio = simulate_share(
            intervals, mid, scale=scale, load_fn=load_fn
        )
        if ratio <= max_unused_ratio:
            best = mid
            low = mid
        else:
            high = mid
    return best


def energy_weighted_percentile(
    intervals: list[ArchiveInterval],
    *,
    scale: float,
    load_fn: Any,
    percentile: float,
) -> float | None:
    """Energy-weighted percentile of ideal share on scaled export."""
    samples: list[tuple[float, float]] = []
    for interval in intervals:
        export = interval.provider_export_kwh
        if export is None or export <= 0:
            continue
        scaled_export = export * scale
        if scaled_export <= 0:
            continue
        load = float(load_fn(interval))
        ideal = clamp(100.0 * load / scaled_export, 0.0, 100.0)
        samples.append((ideal, scaled_export))
    if not samples:
        return None
    samples.sort(key=lambda item: item[0])
    total_weight = sum(weight for _value, weight in samples)
    if total_weight <= 0:
        return None
    threshold = total_weight * percentile / 100.0
    cumulative = 0.0
    chosen = samples[-1][0]
    for value, weight in samples:
        cumulative += weight
        if cumulative >= threshold:
            chosen = value
            break
    return chosen


def _reference_month(intervals: list[ArchiveInterval], now: datetime) -> datetime:
    local = as_aware_local(now)
    current_start = start_of_month(local)
    current_count = 0
    previous_start = add_months(current_start, -1)
    for interval in intervals:
        if not is_daylight(interval):
            continue
        end_local = as_aware_local(interval.interval_end)
        if end_local >= current_start:
            current_count += 1
    if current_count >= RECOMMEND_MIN_DAYLIGHT_INTERVALS:
        return current_start
    return previous_start


def recommend_next_month_share(
    intervals: list[ArchiveInterval],
    *,
    now: datetime,
    options: dict[str, Any] | None = None,
    target_month: str | None = None,
) -> ShareRecommendation:
    """Recommend conservative and optimistic % for the next Moj Elektro month."""
    local_now = as_aware_local(now)
    obs_start, obs_end = observation_window(local_now)
    default_target = add_months(start_of_month(local_now), 1)
    target = parse_year_month(target_month, default_target)
    daylight = [
        interval
        for interval in intervals
        if is_daylight(interval)
        and dt_util.as_utc(obs_start)
        <= dt_util.as_utc(interval.interval_end)
        < dt_util.as_utc(obs_end) + timedelta(seconds=1)
    ]
    if intervals and not daylight:
        daylight = [interval for interval in intervals if is_daylight(interval)]
    curve, curve_source = resolve_production_curve(options)
    reference = _reference_month(daylight, local_now)
    scale = seasonal_scale(curve, reference.month, target.month)
    deadline = local_now.replace(
        day=MOJ_ELEKTRO_DEADLINE_DAY, hour=0, minute=0, second=0, microsecond=0
    )

    conservative = largest_share_within_unused_ratio(
        daylight,
        scale=scale,
        load_fn=organic_load_kwh,
        max_unused_ratio=RECOMMEND_UNUSED_RATIO_CONSERVATIVE,
    )
    optimistic = largest_share_within_unused_ratio(
        daylight,
        scale=scale,
        load_fn=optimistic_load_kwh,
        max_unused_ratio=RECOMMEND_UNUSED_RATIO_OPTIMISTIC,
    )
    fallback_used = False
    if conservative is None:
        conservative = energy_weighted_percentile(
            daylight, scale=scale, load_fn=organic_load_kwh, percentile=50.0
        )
        fallback_used = conservative is not None
    if optimistic is None:
        optimistic = energy_weighted_percentile(
            daylight, scale=scale, load_fn=optimistic_load_kwh, percentile=75.0
        )
        fallback_used = fallback_used or optimistic is not None

    if conservative is not None:
        conservative = _round_share(conservative)
    if optimistic is not None:
        optimistic = _round_share(optimistic)
    if (
        conservative is not None
        and optimistic is not None
        and conservative > optimistic
    ):
        conservative = optimistic

    cons_unused = cons_coverage = opt_unused = opt_coverage = None
    if conservative is not None:
        cons_unused, cons_coverage, _ratio = simulate_share(
            daylight, conservative, scale=scale, load_fn=organic_load_kwh
        )
    if optimistic is not None:
        opt_unused, opt_coverage, _ratio = simulate_share(
            daylight, optimistic, scale=scale, load_fn=optimistic_load_kwh
        )

    return ShareRecommendation(
        target_month=format_year_month(target),
        deadline_date=deadline.date().isoformat(),
        deadline_passed=local_now.day > MOJ_ELEKTRO_DEADLINE_DAY,
        reference_month=format_year_month(reference),
        seasonal_scale=round(scale, 6),
        observation_start=obs_start.isoformat(),
        observation_end=obs_end.isoformat(),
        daylight_intervals=len(daylight),
        conservative_pct=conservative,
        optimistic_pct=optimistic,
        conservative_unused_kwh=cons_unused,
        conservative_coverage_pct=cons_coverage,
        optimistic_unused_kwh=opt_unused,
        optimistic_coverage_pct=opt_coverage,
        production_curve_source=curve_source,
        fallback_used=fallback_used,
    )
