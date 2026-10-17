"""Compact interval archive for analysis export and recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import ARCHIVE_RETENTION_DAYS, ARCHIVE_STORAGE_KEY, ARCHIVE_STORAGE_VERSION
from .models import IntervalResult


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class ArchiveLoadSnapshot:
    """Per-load snapshot captured at settlement time."""

    switch_entity_id: str
    energy_wh: float
    target_wh: float
    idle_latched: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "switch_entity_id": self.switch_entity_id,
            "energy_wh": self.energy_wh,
            "target_wh": self.target_wh,
            "idle_latched": self.idle_latched,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchiveLoadSnapshot | None:
        switch_entity_id = data.get("switch_entity_id")
        if not isinstance(switch_entity_id, str) or not switch_entity_id:
            return None
        return cls(
            switch_entity_id=switch_entity_id,
            energy_wh=_safe_float(data.get("energy_wh", 0.0), 0.0),
            target_wh=_safe_float(data.get("target_wh", 0.0), 0.0),
            idle_latched=bool(data.get("idle_latched", False)),
        )


@dataclass(slots=True)
class ArchiveInterval:
    """One persisted settlement interval for export and recommendations."""

    interval_id: str
    interval_start: datetime
    interval_end: datetime
    provider_export_kwh: float | None
    receiver_import_kwh: float
    shared_energy_kwh: float
    unused_shared_kwh: float
    used_shared_kwh: float
    fixed_allocation_percentage: float | None
    active_load_kwh: float
    mopped_wh: float | None = None
    loads: list[ArchiveLoadSnapshot] = field(default_factory=list)
    source: str = "settlement"

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_id": self.interval_id,
            "interval_start": self.interval_start.isoformat(),
            "interval_end": self.interval_end.isoformat(),
            "provider_export_kwh": self.provider_export_kwh,
            "receiver_import_kwh": self.receiver_import_kwh,
            "shared_energy_kwh": self.shared_energy_kwh,
            "unused_shared_kwh": self.unused_shared_kwh,
            "used_shared_kwh": self.used_shared_kwh,
            "fixed_allocation_percentage": self.fixed_allocation_percentage,
            "active_load_kwh": self.active_load_kwh,
            "mopped_wh": self.mopped_wh,
            "loads": [load.to_dict() for load in self.loads],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchiveInterval | None:
        interval_id = data.get("interval_id")
        start = dt_util.parse_datetime(str(data.get("interval_start", "")))
        end = dt_util.parse_datetime(str(data.get("interval_end", "")))
        if not isinstance(interval_id, str) or start is None or end is None:
            return None
        loads: list[ArchiveLoadSnapshot] = []
        raw_loads = data.get("loads")
        if isinstance(raw_loads, list):
            for item in raw_loads:
                if not isinstance(item, dict):
                    continue
                parsed = ArchiveLoadSnapshot.from_dict(item)
                if parsed is not None:
                    loads.append(parsed)
        return cls(
            interval_id=interval_id,
            interval_start=start,
            interval_end=end,
            provider_export_kwh=_optional_float(data.get("provider_export_kwh")),
            receiver_import_kwh=_safe_float(data.get("receiver_import_kwh", 0.0), 0.0),
            shared_energy_kwh=_safe_float(data.get("shared_energy_kwh", 0.0), 0.0),
            unused_shared_kwh=_safe_float(data.get("unused_shared_kwh", 0.0), 0.0),
            used_shared_kwh=_safe_float(data.get("used_shared_kwh", 0.0), 0.0),
            fixed_allocation_percentage=_optional_float(
                data.get("fixed_allocation_percentage")
            ),
            active_load_kwh=_safe_float(data.get("active_load_kwh", 0.0), 0.0),
            mopped_wh=_optional_float(data.get("mopped_wh")),
            loads=loads,
            source=str(data.get("source") or "settlement"),
        )


def archive_interval_from_result(
    result: IntervalResult,
    *,
    alc_snapshot: dict[str, Any] | None = None,
    source: str = "settlement",
) -> ArchiveInterval:
    """Build an archive row from a processed interval result."""
    loads: list[ArchiveLoadSnapshot] = []
    mopped_wh: float | None = None
    if isinstance(alc_snapshot, dict):
        mopped_wh = _optional_float(alc_snapshot.get("mopped_wh"))
        raw_loads = alc_snapshot.get("loads")
        if isinstance(raw_loads, list):
            for item in raw_loads:
                if not isinstance(item, dict):
                    continue
                parsed = ArchiveLoadSnapshot.from_dict(item)
                if parsed is not None:
                    loads.append(parsed)
    if mopped_wh is None and result.active_load_interval_kwh > 0:
        mopped_wh = result.active_load_interval_kwh * 1000.0
    return ArchiveInterval(
        interval_id=result.interval_id,
        interval_start=result.interval_start,
        interval_end=result.interval_end,
        provider_export_kwh=result.provider_export_interval_kwh,
        receiver_import_kwh=result.receiver_import_interval_kwh,
        shared_energy_kwh=result.shared_energy_interval_kwh,
        unused_shared_kwh=result.unused_shared_kwh,
        used_shared_kwh=result.used_shared_kwh,
        fixed_allocation_percentage=result.fixed_allocation_percentage,
        active_load_kwh=result.active_load_interval_kwh,
        mopped_wh=mopped_wh,
        loads=loads,
        source=source,
    )


def prune_archive_intervals(
    intervals: list[ArchiveInterval],
    *,
    newest_end: datetime,
    retention_days: int = ARCHIVE_RETENTION_DAYS,
) -> list[ArchiveInterval]:
    """Drop intervals older than the retention window."""
    cutoff = dt_util.as_utc(newest_end) - timedelta(days=retention_days)
    return [
        interval
        for interval in intervals
        if dt_util.as_utc(interval.interval_end) >= cutoff
    ]


def append_archive_interval(
    intervals: list[ArchiveInterval],
    row: ArchiveInterval,
    *,
    retention_days: int = ARCHIVE_RETENTION_DAYS,
) -> list[ArchiveInterval]:
    """Append or replace one interval and prune expired rows."""
    replaced = False
    next_rows: list[ArchiveInterval] = []
    for existing in intervals:
        if existing.interval_id == row.interval_id:
            next_rows.append(row)
            replaced = True
        else:
            next_rows.append(existing)
    if not replaced:
        next_rows.append(row)
    next_rows.sort(key=lambda item: dt_util.as_utc(item.interval_end))
    return prune_archive_intervals(
        next_rows, newest_end=row.interval_end, retention_days=retention_days
    )


def intervals_in_range(
    intervals: list[ArchiveInterval],
    start: datetime,
    end: datetime,
) -> list[ArchiveInterval]:
    """Return intervals whose end is within [start, end)."""
    start_utc = dt_util.as_utc(start)
    end_utc = dt_util.as_utc(end)
    return [
        interval
        for interval in intervals
        if start_utc <= dt_util.as_utc(interval.interval_end) < end_utc
    ]


class IntervalArchive:
    """Separate Store-backed archive of settlement intervals."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            ARCHIVE_STORAGE_VERSION,
            f"{ARCHIVE_STORAGE_KEY}.{entry_id}",
        )
        self.intervals: list[ArchiveInterval] = []

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self.intervals = []
        if not isinstance(stored, dict):
            return
        raw = stored.get("intervals")
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            parsed = ArchiveInterval.from_dict(item)
            if parsed is not None:
                self.intervals.append(parsed)
        self.intervals.sort(key=lambda item: dt_util.as_utc(item.interval_end))

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "version": ARCHIVE_STORAGE_VERSION,
                "intervals": [interval.to_dict() for interval in self.intervals],
            }
        )

    async def async_append(self, row: ArchiveInterval) -> None:
        self.intervals = append_archive_interval(self.intervals, row)
        await self.async_save()

    def get_range(self, start: datetime, end: datetime) -> list[ArchiveInterval]:
        return intervals_in_range(self.intervals, start, end)
