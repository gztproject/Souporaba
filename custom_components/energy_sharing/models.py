"""Data models for the Energy Sharing integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    RECONCILIATION_NOT_CONFIGURED,
    STORAGE_VERSION,
)


@dataclass(slots=True)
class IntervalResult:
    """Calculated values for one completed interval."""

    interval_id: str
    interval_start: datetime
    interval_end: datetime
    provider_exported_kwh: float
    receiver_imported_kwh: float
    calculated_allocated_kwh: float
    used_shared_kwh: float
    unused_shared_kwh: float
    billable_grid_kwh: float
    allocation_percentage: float
    required_share_pct: float | None
    ideal_share_pct: float | None
    allocation_utilization_pct: float | None
    consumption_coverage_pct: float | None
    reconciliation_status: str
    provider_export_source: str
    receiver_import_source: str
    processed_at: datetime
    reported_allocated_kwh: float | None = None
    allocation_difference_kwh: float | None = None
    allocation_difference_pct: float | None = None
    reported_allocation_source: str | None = None
    allocation_percentage_source: str | None = None

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
            provider_exported_kwh=float(data["provider_exported_kwh"]),
            receiver_imported_kwh=float(data["receiver_imported_kwh"]),
            calculated_allocated_kwh=float(data["calculated_allocated_kwh"]),
            used_shared_kwh=float(data["used_shared_kwh"]),
            unused_shared_kwh=float(data["unused_shared_kwh"]),
            billable_grid_kwh=float(data["billable_grid_kwh"]),
            allocation_percentage=float(data["allocation_percentage"]),
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
            reconciliation_status=data.get(
                "reconciliation_status", RECONCILIATION_NOT_CONFIGURED
            ),
            provider_export_source=data["provider_export_source"],
            receiver_import_source=data["receiver_import_source"],
            processed_at=dt_util.parse_datetime(data["processed_at"])
            or dt_util.utcnow(),
            reported_allocated_kwh=(
                float(data["reported_allocated_kwh"])
                if data.get("reported_allocated_kwh") is not None
                else None
            ),
            allocation_difference_kwh=(
                float(data["allocation_difference_kwh"])
                if data.get("allocation_difference_kwh") is not None
                else None
            ),
            allocation_difference_pct=(
                float(data["allocation_difference_pct"])
                if data.get("allocation_difference_pct") is not None
                else None
            ),
            reported_allocation_source=data.get("reported_allocation_source"),
            allocation_percentage_source=data.get("allocation_percentage_source"),
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
    cumulative_provider_export: float = 0.0
    cumulative_receiver_import: float = 0.0
    cumulative_calculated_allocated: float = 0.0
    cumulative_used: float = 0.0
    cumulative_unused: float = 0.0
    cumulative_billable: float = 0.0
    processed_intervals: int = 0
    skipped_intervals: int = 0
    reconciliation_mismatch_count: int = 0
    last_skip: SkipRecord | None = None
    last_interval: IntervalResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "version": self.version,
            "last_processed_interval_id": self.last_processed_interval_id,
            "cumulative_provider_export": self.cumulative_provider_export,
            "cumulative_receiver_import": self.cumulative_receiver_import,
            "cumulative_calculated_allocated": self.cumulative_calculated_allocated,
            "cumulative_used": self.cumulative_used,
            "cumulative_unused": self.cumulative_unused,
            "cumulative_billable": self.cumulative_billable,
            "processed_intervals": self.processed_intervals,
            "skipped_intervals": self.skipped_intervals,
            "reconciliation_mismatch_count": self.reconciliation_mismatch_count,
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
            cumulative_provider_export=float(
                data.get("cumulative_provider_export", 0.0)
            ),
            cumulative_receiver_import=float(
                data.get("cumulative_receiver_import", 0.0)
            ),
            cumulative_calculated_allocated=float(
                data.get("cumulative_calculated_allocated", 0.0)
            ),
            cumulative_used=float(data.get("cumulative_used", 0.0)),
            cumulative_unused=float(data.get("cumulative_unused", 0.0)),
            cumulative_billable=float(data.get("cumulative_billable", 0.0)),
            processed_intervals=int(data.get("processed_intervals", 0)),
            skipped_intervals=int(data.get("skipped_intervals", 0)),
            reconciliation_mismatch_count=int(
                data.get("reconciliation_mismatch_count", 0)
            ),
            last_skip=SkipRecord.from_dict(last_skip) if last_skip else None,
            last_interval=(
                IntervalResult.from_dict(last_interval) if last_interval else None
            ),
        )


def migrate_storage(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate storage data to the current schema version."""
    migrated = dict(data)

    if from_version < 2:
        migrated["cumulative_receiver_import"] = migrated.pop(
            "cumulative_imported", 0.0
        )
        migrated["cumulative_calculated_allocated"] = migrated.pop(
            "cumulative_shared", 0.0
        )
        migrated["cumulative_provider_export"] = 0.0
        migrated["reconciliation_mismatch_count"] = 0
        migrated["last_interval"] = None
        migrated["last_processed_interval_id"] = None
        migrated["version"] = 2

    migrated["version"] = STORAGE_VERSION
    return migrated


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value to the given range."""
    return max(minimum, min(value, maximum))


def calculate_interval(
    provider_exported_kwh: float,
    receiver_imported_kwh: float,
    allocation_percentage: float,
) -> dict[str, float | None]:
    """Calculate settlement values for one interval."""
    calculated_allocated_kwh = (
        provider_exported_kwh * allocation_percentage / 100.0
    )

    used_shared_kwh = min(calculated_allocated_kwh, receiver_imported_kwh)
    unused_shared_kwh = max(calculated_allocated_kwh - receiver_imported_kwh, 0.0)
    billable_grid_kwh = max(receiver_imported_kwh - calculated_allocated_kwh, 0.0)

    required_share_pct: float | None = None
    ideal_share_pct: float | None = None
    if provider_exported_kwh > 0:
        required_share_pct = 100.0 * receiver_imported_kwh / provider_exported_kwh
        ideal_share_pct = clamp(required_share_pct, 0.0, 100.0)

    allocation_utilization_pct: float | None = None
    if calculated_allocated_kwh > 0:
        allocation_utilization_pct = (
            100.0 * used_shared_kwh / calculated_allocated_kwh
        )

    consumption_coverage_pct: float | None = None
    if receiver_imported_kwh > 0:
        consumption_coverage_pct = 100.0 * used_shared_kwh / receiver_imported_kwh

    return {
        "calculated_allocated_kwh": calculated_allocated_kwh,
        "used_shared_kwh": used_shared_kwh,
        "unused_shared_kwh": unused_shared_kwh,
        "billable_grid_kwh": billable_grid_kwh,
        "required_share_pct": required_share_pct,
        "ideal_share_pct": ideal_share_pct,
        "allocation_utilization_pct": allocation_utilization_pct,
        "consumption_coverage_pct": consumption_coverage_pct,
    }


def evaluate_reconciliation(
    calculated_allocated_kwh: float,
    reported_allocated_kwh: float,
    tolerance_kwh: float,
    tolerance_pct: float,
) -> dict[str, float | bool]:
    """Evaluate optional reported allocation reconciliation.

    Reconciliation passes when either:
    - abs(reported - calculated) <= tolerance_kwh, OR
    - allocation_difference_pct <= tolerance_pct
    where allocation_difference_pct = 100 * abs(diff) / calculated when calculated > 0.
    """
    difference_kwh = reported_allocated_kwh - calculated_allocated_kwh
    difference_pct: float | None = None
    if calculated_allocated_kwh > 0:
        difference_pct = 100.0 * abs(difference_kwh) / calculated_allocated_kwh

    within_kwh = abs(difference_kwh) <= tolerance_kwh
    within_pct = (
        difference_pct is not None and difference_pct <= tolerance_pct
    )
    reconciled = within_kwh or within_pct

    return {
        "allocation_difference_kwh": difference_kwh,
        "allocation_difference_pct": (
            difference_pct if difference_pct is not None else 0.0
        ),
        "reconciled": reconciled,
    }


@dataclass(slots=True)
class EnergySharingRuntimeData:
    """Runtime data stored on the config entry."""

    manager: Any = field(repr=False)
