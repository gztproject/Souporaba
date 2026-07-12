"""Data models for the Energy Sharing integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import STORAGE_VERSION


@dataclass(slots=True)
class IntervalResult:
    """Calculated values for one completed interval."""

    interval_id: str
    interval_start: datetime
    interval_end: datetime
    imported_kwh: float
    shared_kwh: float
    exported_kwh: float | None
    used_kwh: float
    unused_kwh: float
    billable_kwh: float
    required_share_pct: float | None
    ideal_share_pct: float | None
    allocation_utilization_pct: float | None
    consumption_coverage_pct: float | None
    allocation_percentage: float
    grid_import_entity: str
    shared_energy_entity: str
    processed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        data = asdict(self)
        data["interval_start"] = self.interval_start.isoformat()
        data["interval_end"] = self.interval_end.isoformat()
        data["processed_at"] = self.processed_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntervalResult:
        """Deserialize from storage."""
        return cls(
            interval_id=data["interval_id"],
            interval_start=dt_util.parse_datetime(data["interval_start"])
            or dt_util.utcnow(),
            interval_end=dt_util.parse_datetime(data["interval_end"])
            or dt_util.utcnow(),
            imported_kwh=float(data["imported_kwh"]),
            shared_kwh=float(data["shared_kwh"]),
            exported_kwh=(
                float(data["exported_kwh"])
                if data.get("exported_kwh") is not None
                else None
            ),
            used_kwh=float(data["used_kwh"]),
            unused_kwh=float(data["unused_kwh"]),
            billable_kwh=float(data["billable_kwh"]),
            required_share_pct=(
                float(data["required_share_pct"])
                if data.get("required_share_pct") is not None
                else None
            ),
            ideal_share_pct=(
                float(data["ideal_share_pct"])
                if data.get("ideal_share_pct") is not None
                else None
            ),
            allocation_utilization_pct=(
                float(data["allocation_utilization_pct"])
                if data.get("allocation_utilization_pct") is not None
                else None
            ),
            consumption_coverage_pct=(
                float(data["consumption_coverage_pct"])
                if data.get("consumption_coverage_pct") is not None
                else None
            ),
            allocation_percentage=float(data["allocation_percentage"]),
            grid_import_entity=data["grid_import_entity"],
            shared_energy_entity=data["shared_energy_entity"],
            processed_at=dt_util.parse_datetime(data["processed_at"])
            or dt_util.utcnow(),
        )


@dataclass(slots=True)
class SkipRecord:
    """Record of a skipped interval."""

    timestamp: datetime
    reason: str
    interval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "interval_id": self.interval_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkipRecord:
        """Deserialize from storage."""
        return cls(
            timestamp=dt_util.parse_datetime(data["timestamp"]) or dt_util.utcnow(),
            reason=data["reason"],
            interval_id=data.get("interval_id"),
        )


@dataclass
class StorageData:
    """Persistent integration storage."""

    version: int = STORAGE_VERSION
    last_processed_interval_id: str | None = None
    cumulative_imported: float = 0.0
    cumulative_shared: float = 0.0
    cumulative_used: float = 0.0
    cumulative_unused: float = 0.0
    cumulative_billable: float = 0.0
    processed_intervals: int = 0
    skipped_intervals: int = 0
    last_skip: SkipRecord | None = None
    last_interval: IntervalResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "version": self.version,
            "last_processed_interval_id": self.last_processed_interval_id,
            "cumulative_imported": self.cumulative_imported,
            "cumulative_shared": self.cumulative_shared,
            "cumulative_used": self.cumulative_used,
            "cumulative_unused": self.cumulative_unused,
            "cumulative_billable": self.cumulative_billable,
            "processed_intervals": self.processed_intervals,
            "skipped_intervals": self.skipped_intervals,
            "last_skip": self.last_skip.to_dict() if self.last_skip else None,
            "last_interval": (
                self.last_interval.to_dict() if self.last_interval else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StorageData:
        """Deserialize from storage with migration support."""
        version = int(data.get("version", 1))
        if version != STORAGE_VERSION:
            data = migrate_storage(data, version)

        last_skip = data.get("last_skip")
        last_interval = data.get("last_interval")

        return cls(
            version=STORAGE_VERSION,
            last_processed_interval_id=data.get("last_processed_interval_id"),
            cumulative_imported=float(data.get("cumulative_imported", 0.0)),
            cumulative_shared=float(data.get("cumulative_shared", 0.0)),
            cumulative_used=float(data.get("cumulative_used", 0.0)),
            cumulative_unused=float(data.get("cumulative_unused", 0.0)),
            cumulative_billable=float(data.get("cumulative_billable", 0.0)),
            processed_intervals=int(data.get("processed_intervals", 0)),
            skipped_intervals=int(data.get("skipped_intervals", 0)),
            last_skip=SkipRecord.from_dict(last_skip) if last_skip else None,
            last_interval=(
                IntervalResult.from_dict(last_interval) if last_interval else None
            ),
        )


def migrate_storage(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate storage data to the current schema version."""
    migrated = dict(data)
    if from_version < 1:
        migrated["version"] = 1
    return migrated


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value to the given range."""
    return max(minimum, min(value, maximum))


def calculate_interval(
    imported_kwh: float,
    shared_kwh: float,
    allocation_percentage: float,
) -> dict[str, float | None]:
    """Calculate settlement values for one interval."""
    exported_kwh: float | None = None
    if allocation_percentage > 0:
        exported_kwh = shared_kwh * 100.0 / allocation_percentage

    used_kwh = min(shared_kwh, imported_kwh)
    unused_kwh = max(shared_kwh - imported_kwh, 0.0)
    billable_kwh = max(imported_kwh - shared_kwh, 0.0)

    required_share_pct: float | None = None
    ideal_share_pct: float | None = None
    if exported_kwh is not None and exported_kwh > 0:
        required_share_pct = 100.0 * imported_kwh / exported_kwh
        ideal_share_pct = clamp(required_share_pct, 0.0, 100.0)

    allocation_utilization_pct: float | None = None
    if shared_kwh > 0:
        allocation_utilization_pct = 100.0 * used_kwh / shared_kwh

    consumption_coverage_pct: float | None = None
    if imported_kwh > 0:
        consumption_coverage_pct = 100.0 * used_kwh / imported_kwh

    return {
        "exported_kwh": exported_kwh,
        "used_kwh": used_kwh,
        "unused_kwh": unused_kwh,
        "billable_kwh": billable_kwh,
        "required_share_pct": required_share_pct,
        "ideal_share_pct": ideal_share_pct,
        "allocation_utilization_pct": allocation_utilization_pct,
        "consumption_coverage_pct": consumption_coverage_pct,
    }


@dataclass(slots=True)
class EnergySharingRuntimeData:
    """Runtime data stored on the config entry."""

    manager: Any = field(repr=False)
