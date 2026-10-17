"""Analysis export pack: period resolution, CSV generation, and file writing."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .archive import ArchiveInterval
from .const import (
    DEFAULT_EXPORT_PERIOD,
    DOMAIN,
    PERIOD_CUSTOM,
    PERIOD_LAST_7_DAYS,
    PERIOD_LAST_MONTH,
    PERIOD_THIS_MONTH,
    PERIOD_THIS_YEAR,
)
from .recommend import ShareRecommendation, add_months, as_aware_local, start_of_month

_LOGGER = logging.getLogger(__name__)

SETTLEMENT_FIELDS = (
    "interval_start",
    "interval_end",
    "provider_export_kwh",
    "receiver_import_kwh",
    "shared_energy_kwh",
    "unused_shared_kwh",
    "used_shared_kwh",
    "fixed_allocation_percentage",
)
ENERGY_FIELDS = (
    "date",
    "provider_export_kwh",
    "shared_energy_kwh",
    "export_after_sharing_kwh",
    "ytd_export_kwh",
    "ytd_shared_kwh",
    "ytd_export_after_sharing_kwh",
)
ACTIVE_LOAD_FIELDS = (
    "interval_start",
    "interval_end",
    "switch_entity_id",
    "energy_wh",
    "target_wh",
    "mopped_wh",
    "idle_latched",
)
NEXT_MONTH_FIELDS = (
    "target_month",
    "deadline_date",
    "deadline_passed",
    "reference_month",
    "seasonal_scale",
    "observation_start",
    "observation_end",
    "daylight_intervals",
    "conservative_pct",
    "optimistic_pct",
    "conservative_unused_kwh",
    "conservative_coverage_pct",
    "optimistic_unused_kwh",
    "optimistic_coverage_pct",
    "production_curve_source",
)

RECORDER_SENSOR_KEYS = (
    "provider_export_last_interval",
    "receiver_import_last_interval",
    "shared_energy_last_interval",
    "unused_shared_last_interval",
    "used_shared_last_interval",
)

_RECORDER_FIELD_MAP = {
    "provider_export_last_interval": "provider_export_kwh",
    "receiver_import_last_interval": "receiver_import_kwh",
    "shared_energy_last_interval": "shared_energy_kwh",
    "unused_shared_last_interval": "unused_shared_kwh",
    "used_shared_last_interval": "used_shared_kwh",
}

ENERGY_CSV_COMMENTS = (
    "Donor daily energy from Oddajnik grid export and shared energy only.",
    "Production and Oddajnik grid import are not available on this instance.",
    "This is not a full EZ-1 annual net-metering reserve.",
    "export_after_sharing = provider_export - shared (allocated share deducted).",
)

NEXT_MONTH_COMMENTS = (
    "Recommended Moj Elektro share % for the next month (submit by the 10th).",
    "Conservative: house load only, unused/expected <= 5%.",
    "Optimistic: ALC mop-up except tank-full intervals; unused/expected <= 15%.",
    "Export is seasonally scaled; receiver import is measured as-is.",
    "Not a registration. Copy the chosen % into Moj Elektro, then the Number.",
)


@dataclass(slots=True)
class ExportPeriod:
    """Resolved local start/end for an analysis pack."""

    period: str
    start: datetime
    end: datetime


@dataclass(slots=True)
class ExportPackResult:
    """Written pack locations and summary counts."""

    folder: str
    zip_path: str
    settlement_rows: int
    energy_rows: int
    active_load_rows: int
    active_loads_included: bool
    archive_intervals: int
    recorder_intervals: int
    recommendation: dict[str, Any] | None


def resolve_export_period(
    period: str | None,
    start: datetime | None,
    end: datetime | None,
    now: datetime,
) -> ExportPeriod:
    """Resolve a named period or custom start/end in the HA local timezone."""
    local_now = as_aware_local(now)
    selected = period or DEFAULT_EXPORT_PERIOD
    if selected == PERIOD_CUSTOM:
        if start is None or end is None:
            raise HomeAssistantError("custom_period_requires_start_end")
        custom_start = as_aware_local(start)
        custom_end = as_aware_local(end)
        if custom_end <= custom_start:
            raise HomeAssistantError("custom_period_invalid_range")
        return ExportPeriod(period=selected, start=custom_start, end=custom_end)

    if selected == PERIOD_LAST_7_DAYS:
        return ExportPeriod(
            period=selected, start=local_now - timedelta(days=7), end=local_now
        )
    if selected == PERIOD_THIS_MONTH:
        return ExportPeriod(
            period=selected, start=start_of_month(local_now), end=local_now
        )
    if selected == PERIOD_THIS_YEAR:
        year_start = local_now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return ExportPeriod(period=selected, start=year_start, end=local_now)
    if selected == PERIOD_LAST_MONTH:
        this_month = start_of_month(local_now)
        previous = add_months(this_month, -1)
        return ExportPeriod(period=selected, start=previous, end=this_month)
    raise HomeAssistantError("unknown_export_period")


def merge_archive_and_recorder(
    archive_rows: list[ArchiveInterval],
    recorder_rows: list[ArchiveInterval],
) -> list[ArchiveInterval]:
    """Prefer archive rows; fill gaps from Recorder reconstructions."""
    merged: dict[str, ArchiveInterval] = {}
    for row in recorder_rows:
        merged[_row_key(row)] = row
    for row in archive_rows:
        merged[_row_key(row)] = row
    return sorted(merged.values(), key=lambda item: dt_util.as_utc(item.interval_end))


def _row_key(row: ArchiveInterval) -> str:
    return row.interval_id or dt_util.as_utc(row.interval_end).isoformat()


def build_settlement_rows(intervals: list[ArchiveInterval]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for interval in intervals:
        rows.append(
            {
                "interval_start": interval.interval_start.isoformat(),
                "interval_end": interval.interval_end.isoformat(),
                "provider_export_kwh": _fmt_optional(interval.provider_export_kwh),
                "receiver_import_kwh": interval.receiver_import_kwh,
                "shared_energy_kwh": interval.shared_energy_kwh,
                "unused_shared_kwh": interval.unused_shared_kwh,
                "used_shared_kwh": interval.used_shared_kwh,
                "fixed_allocation_percentage": _fmt_optional(
                    interval.fixed_allocation_percentage
                ),
            }
        )
    return rows


def daily_energy_from_intervals(
    intervals: list[ArchiveInterval],
    tzinfo: tzinfo | None,
) -> dict[str, dict[str, float]]:
    """Sum 15-minute archive rows into local calendar days."""
    daily: dict[str, dict[str, float]] = {}
    for interval in intervals:
        local_end = interval.interval_end
        if tzinfo is not None:
            local_end = interval.interval_end.astimezone(tzinfo)
        day = local_end.date().isoformat()
        bucket = daily.setdefault(
            day,
            {"provider_export_kwh": 0.0, "shared_energy_kwh": 0.0},
        )
        if interval.provider_export_kwh is not None:
            bucket["provider_export_kwh"] += interval.provider_export_kwh
        bucket["shared_energy_kwh"] += interval.shared_energy_kwh
    return daily


def build_energy_rows(
    daily: dict[str, dict[str, float]],
    period_start: datetime,
    period_end: datetime,
) -> list[dict[str, Any]]:
    """Build energy.csv rows for the period with YTD running totals."""
    if not daily:
        return []
    start_date = period_start.date()
    if (
        period_end.hour == 0
        and period_end.minute == 0
        and period_end.second == 0
        and period_end.microsecond == 0
    ):
        last_date = (period_end - timedelta(days=1)).date()
    else:
        last_date = period_end.date()
    ytd_export = 0.0
    ytd_shared = 0.0
    rows: list[dict[str, Any]] = []
    for day in sorted(daily):
        values = daily[day]
        export = float(values.get("provider_export_kwh", 0.0))
        shared = float(values.get("shared_energy_kwh", 0.0))
        after = export - shared
        ytd_export += export
        ytd_shared += shared
        day_date = datetime.fromisoformat(day).date()
        if day_date < start_date or day_date > last_date:
            continue
        rows.append(
            {
                "date": day,
                "provider_export_kwh": export,
                "shared_energy_kwh": shared,
                "export_after_sharing_kwh": after,
                "ytd_export_kwh": ytd_export,
                "ytd_shared_kwh": ytd_shared,
                "ytd_export_after_sharing_kwh": ytd_export - ytd_shared,
            }
        )
    return rows


def build_active_load_rows(intervals: list[ArchiveInterval]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for interval in intervals:
        if not interval.loads:
            continue
        for load in interval.loads:
            rows.append(
                {
                    "interval_start": interval.interval_start.isoformat(),
                    "interval_end": interval.interval_end.isoformat(),
                    "switch_entity_id": load.switch_entity_id,
                    "energy_wh": load.energy_wh,
                    "target_wh": load.target_wh,
                    "mopped_wh": _fmt_optional(interval.mopped_wh),
                    "idle_latched": "true" if load.idle_latched else "false",
                }
            )
    return rows


def build_next_month_rows(recommendation: ShareRecommendation) -> list[dict[str, Any]]:
    data = recommendation.to_dict()
    return [{key: data.get(key) for key in NEXT_MONTH_FIELDS}]


def render_csv(
    fieldnames: tuple[str, ...],
    rows: list[dict[str, Any]],
    comments: tuple[str, ...] = (),
) -> str:
    buffer = io.StringIO()
    for comment in comments:
        buffer.write(f"# {comment}\n")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


def build_manifest_text(
    *,
    period: ExportPeriod,
    archive_count: int,
    recorder_count: int,
    active_loads_included: bool,
    recommendation: ShareRecommendation | None,
) -> str:
    lines = [
        "Energy Sharing analysis export pack",
        f"period={period.period}",
        f"start={period.start.isoformat()}",
        f"end={period.end.isoformat()}",
        f"archive_intervals={archive_count}",
        f"recorder_intervals={recorder_count}",
        f"active_loads_included={active_loads_included}",
        "Donor energy.csv uses grid export and shared energy only.",
        "No Oddajnik production or import; not a full EZ-1 reserve.",
    ]
    if recommendation is None:
        lines.append("next_month_share=unavailable")
    else:
        lines.append(f"target_month={recommendation.target_month}")
        lines.append(f"deadline_passed={recommendation.deadline_passed}")
        lines.append(f"seasonal_scale={recommendation.seasonal_scale}")
        lines.append(
            f"production_curve_source={recommendation.production_curve_source}"
        )
        lines.append(
            "Conservative unused/expected <= 5% on organic (house) load."
        )
        lines.append(
            "Optimistic unused/expected <= 15% with ALC except tank-full."
        )
    return "\n".join(lines) + "\n"


def resolve_export_directory(hass: HomeAssistant) -> Path:
    """Write under authenticated Media when available, else config/."""
    media_dirs = getattr(hass.config, "media_dirs", None) or {}
    if isinstance(media_dirs, dict) and media_dirs:
        base = media_dirs.get("local") or next(iter(media_dirs.values()))
        return Path(base) / "energy_sharing"
    return Path(hass.config.path("energy_sharing_exports"))


def write_export_pack(
    directory: Path,
    *,
    stamp: str,
    files: dict[str, str],
) -> tuple[Path, Path]:
    """Write CSVs into a timestamped folder and zip them."""
    folder = directory / stamp
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")
    zip_path = directory / f"{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(folder / name, arcname=f"{stamp}/{name}")
    return folder, zip_path


def lookup_sensor_entity_id(hass: HomeAssistant, entry_id: str, key: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_{key}")


async def async_recorder_interval_rows(
    hass: HomeAssistant,
    entry_id: str,
    start: datetime,
    end: datetime,
) -> list[ArchiveInterval]:
    """Reconstruct 15-minute rows from last-interval sensor history."""
    entity_map: dict[str, str] = {}
    for key in RECORDER_SENSOR_KEYS:
        entity_id = lookup_sensor_entity_id(hass, entry_id, key)
        if entity_id:
            entity_map[key] = entity_id
    if not entity_map:
        return []
    try:
        from homeassistant.components.recorder import get_instance, history
    except ImportError:
        return []

    try:
        instance = get_instance(hass)
    except Exception:  # pragma: no cover - recorder not set up
        return []

    def _fetch() -> dict[str, list[Any]]:
        return history.get_significant_states(
            hass,
            dt_util.as_utc(start),
            dt_util.as_utc(end),
            list(entity_map.values()),
            significant_changes_only=False,
            minimal_response=False,
        )

    try:
        states_by_entity = await instance.async_add_executor_job(_fetch)
    except Exception as err:  # pragma: no cover - recorder query failed
        _LOGGER.debug("Recorder history unavailable: %s", err)
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for key, entity_id in entity_map.items():
        field = _RECORDER_FIELD_MAP[key]
        for state in states_by_entity.get(entity_id, []):
            row = _row_from_history_state(state, field)
            if row is None:
                continue
            bucket = grouped.setdefault(row["interval_id"], row)
            bucket[field] = row[field]
            if row.get("interval_start"):
                bucket["interval_start"] = row["interval_start"]
            if row.get("interval_end"):
                bucket["interval_end"] = row["interval_end"]

    intervals: list[ArchiveInterval] = []
    for item in grouped.values():
        start_dt = item.get("interval_start")
        end_dt = item.get("interval_end")
        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
            continue
        intervals.append(
            ArchiveInterval(
                interval_id=str(item["interval_id"]),
                interval_start=start_dt,
                interval_end=end_dt,
                provider_export_kwh=_optional_float(item.get("provider_export_kwh")),
                receiver_import_kwh=float(item.get("receiver_import_kwh") or 0.0),
                shared_energy_kwh=float(item.get("shared_energy_kwh") or 0.0),
                unused_shared_kwh=float(item.get("unused_shared_kwh") or 0.0),
                used_shared_kwh=float(item.get("used_shared_kwh") or 0.0),
                fixed_allocation_percentage=None,
                active_load_kwh=0.0,
                source="recorder",
            )
        )
    return intervals


async def async_recorder_daily_energy(
    hass: HomeAssistant,
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, dict[str, float]]:
    """Daily change statistics for cumulative energy sources."""
    if not entity_ids:
        return {}
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )
    except ImportError:
        return {}
    try:
        instance = get_instance(hass)
    except Exception:  # pragma: no cover
        return {}

    def _fetch() -> Any:
        return statistics_during_period(
            hass,
            dt_util.as_utc(start),
            dt_util.as_utc(end),
            set(entity_ids),
            "day",
            None,
            {"change"},
        )

    try:
        stats = await instance.async_add_executor_job(_fetch)
    except Exception as err:  # pragma: no cover
        _LOGGER.debug("Recorder statistics unavailable: %s", err)
        return {}

    daily: dict[str, dict[str, float]] = {}
    for entity_id, samples in stats.items():
        field = (
            "provider_export_kwh"
            if "export" in entity_id or entity_id == entity_ids[0]
            else "shared_energy_kwh"
        )
        # Caller passes [provider, shared] in that order when both exist.
        if len(entity_ids) >= 2:
            if entity_id == entity_ids[0]:
                field = "provider_export_kwh"
            elif entity_id == entity_ids[1]:
                field = "shared_energy_kwh"
        for sample in samples:
            start_ts = sample.get("start")
            if start_ts is None:
                continue
            if isinstance(start_ts, datetime):
                day = dt_util.as_local(start_ts).date().isoformat()
            else:
                parsed = dt_util.utc_from_timestamp(float(start_ts))
                day = dt_util.as_local(parsed).date().isoformat()
            change = sample.get("change")
            if change is None:
                continue
            daily.setdefault(
                day, {"provider_export_kwh": 0.0, "shared_energy_kwh": 0.0}
            )
            daily[day][field] = float(change)
    return daily


def _row_from_history_state(state: Any, field: str) -> dict[str, Any] | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    attributes = getattr(state, "attributes", {}) or {}
    start = dt_util.parse_datetime(str(attributes.get("interval_start", "")))
    end = dt_util.parse_datetime(str(attributes.get("interval_end", "")))
    last_updated = getattr(state, "last_updated", None)
    if end is None and isinstance(last_updated, datetime):
        end = last_updated
    if start is None and end is not None:
        start = end - timedelta(minutes=15)
    if start is None or end is None:
        return None
    interval_id = attributes.get("interval_id") or (
        f"{dt_util.as_utc(start).isoformat()}|{dt_util.as_utc(end).isoformat()}"
    )
    return {
        "interval_id": str(interval_id),
        "interval_start": start,
        "interval_end": end,
        field: value,
    }


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_optional(value: float | None) -> float | str:
    if value is None:
        return ""
    return value


