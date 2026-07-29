"""Data models for the Energy Sharing integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    EXPORT_TYPE_INFERRED,
    EXPORT_TYPE_MEASURED,
    EXPORT_TYPE_NONE,
    MODE_EXPORT_AND_PERCENTAGE,
    MODE_EXPORT_ONLY,
    MODE_PERCENTAGE_ONLY,
    RECONCILIATION_NOT_CONFIGURED,
    STORAGE_VERSION,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert a value to int with fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class BoundarySnapshot:
    """Cumulative readings at the last accepted interval boundary."""

    interval_id: str
    timestamp: datetime
    receiver_import_total_kwh: float
    shared_energy_total_kwh: float
    provider_export_total_kwh: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "interval_id": self.interval_id,
            "timestamp": self.timestamp.isoformat(),
            "receiver_import_total_kwh": self.receiver_import_total_kwh,
            "shared_energy_total_kwh": self.shared_energy_total_kwh,
            "provider_export_total_kwh": self.provider_export_total_kwh,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoundarySnapshot:
        """Deserialize from storage."""
        return cls(
            interval_id=data["interval_id"],
            timestamp=dt_util.parse_datetime(data["timestamp"]) or dt_util.utcnow(),
            receiver_import_total_kwh=float(data["receiver_import_total_kwh"]),
            shared_energy_total_kwh=float(data["shared_energy_total_kwh"]),
            provider_export_total_kwh=(
                float(data["provider_export_total_kwh"])
                if data.get("provider_export_total_kwh") is not None
                else None
            ),
        )


@dataclass(slots=True)
class SourceResetRecord:
    """Record of a cumulative counter reset."""

    timestamp: datetime
    source_key: str
    entity_id: str
    previous_total_kwh: float
    new_total_kwh: float
    interval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "source_key": self.source_key,
            "entity_id": self.entity_id,
            "previous_total_kwh": self.previous_total_kwh,
            "new_total_kwh": self.new_total_kwh,
            "interval_id": self.interval_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceResetRecord:
        """Deserialize from storage."""
        return cls(
            timestamp=dt_util.parse_datetime(data["timestamp"]) or dt_util.utcnow(),
            source_key=data["source_key"],
            entity_id=data["entity_id"],
            previous_total_kwh=float(data["previous_total_kwh"]),
            new_total_kwh=float(data["new_total_kwh"]),
            interval_id=data.get("interval_id"),
        )


@dataclass(slots=True)
class IntervalResult:
    """Calculated values for one completed interval."""

    interval_id: str
    interval_start: datetime
    interval_end: datetime
    operating_mode: str
    receiver_import_interval_kwh: float
    shared_energy_interval_kwh: float
    used_shared_kwh: float
    unused_shared_kwh: float
    billable_energy_kwh: float
    provider_export_interval_kwh: float | None
    provider_export_source_type: str
    expected_shared_kwh: float | None
    fixed_allocation_percentage: float | None
    effective_allocation_pct: float | None
    required_share_pct: float | None
    ideal_share_pct: float | None
    active_load_interval_kwh: float
    ideal_share_excluding_active_loads_pct: float | None
    allocation_utilization_pct: float | None
    consumption_coverage_pct: float | None
    allocation_difference_kwh: float | None
    allocation_difference_pct: float | None
    reconciliation_status: str
    settlement_accumulated: bool
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
            operating_mode=data["operating_mode"],
            receiver_import_interval_kwh=float(
                data["receiver_import_interval_kwh"]
            ),
            shared_energy_interval_kwh=float(data["shared_energy_interval_kwh"]),
            used_shared_kwh=float(data["used_shared_kwh"]),
            unused_shared_kwh=float(data["unused_shared_kwh"]),
            billable_energy_kwh=float(
                data.get("billable_energy_kwh", data.get("billable_grid_kwh", 0))
            ),
            provider_export_interval_kwh=(
                float(data["provider_export_interval_kwh"])
                if data.get("provider_export_interval_kwh") is not None
                else None
            ),
            provider_export_source_type=data.get(
                "provider_export_source_type", EXPORT_TYPE_NONE
            ),
            expected_shared_kwh=(
                float(data["expected_shared_kwh"])
                if data.get("expected_shared_kwh") is not None
                else None
            ),
            fixed_allocation_percentage=(
                float(data["fixed_allocation_percentage"])
                if data.get("fixed_allocation_percentage") is not None
                else None
            ),
            effective_allocation_pct=(
                float(data["effective_allocation_pct"])
                if data.get("effective_allocation_pct") is not None
                else None
            ),
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
            active_load_interval_kwh=_safe_float(
                data.get("active_load_interval_kwh", 0.0), 0.0
            ),
            ideal_share_excluding_active_loads_pct=(
                float(data["ideal_share_excluding_active_loads_pct"])
                if data.get("ideal_share_excluding_active_loads_pct") is not None
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
            reconciliation_status=data.get(
                "reconciliation_status", RECONCILIATION_NOT_CONFIGURED
            ),
            settlement_accumulated=bool(data.get("settlement_accumulated", True)),
            processed_at=dt_util.parse_datetime(data["processed_at"])
            or dt_util.utcnow(),
        )


@dataclass(slots=True)
class FailureRecord:
    """Record of the most recent failure."""

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
    def from_dict(cls, data: dict[str, Any]) -> FailureRecord:
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
    baseline_initialized: bool = False
    baseline_initialization_count: int = 0
    previous_snapshot: BoundarySnapshot | None = None
    last_processed_interval_id: str | None = None
    last_interval: IntervalResult | None = None
    cumulative_receiver_import: float = 0.0
    cumulative_shared_energy: float = 0.0
    cumulative_provider_export: float = 0.0
    cumulative_expected_shared: float = 0.0
    cumulative_used: float = 0.0
    cumulative_unused: float = 0.0
    cumulative_billable_energy: float = 0.0
    processed_intervals: int = 0
    skipped_intervals: int = 0
    source_reset_count: int = 0
    invalid_reading_count: int = 0
    reconciliation_mismatch_count: int = 0
    last_failure: FailureRecord | None = None
    last_source_reset: SourceResetRecord | None = None
    active_load_estimated_power_w: dict[str, float] = field(default_factory=dict)
    ideal_share_history: list[dict[str, Any]] = field(default_factory=list)
    active_load_cumulative_mopped_up_wh: float = 0.0
    active_load_cumulative_overshoot_wh: float = 0.0
    active_load_cumulative_undershoot_wh: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "version": self.version,
            "baseline_initialized": self.baseline_initialized,
            "baseline_initialization_count": self.baseline_initialization_count,
            "previous_snapshot": (
                self.previous_snapshot.to_dict()
                if self.previous_snapshot
                else None
            ),
            "last_processed_interval_id": self.last_processed_interval_id,
            "last_interval": (
                self.last_interval.to_dict() if self.last_interval else None
            ),
            "cumulative_receiver_import": self.cumulative_receiver_import,
            "cumulative_shared_energy": self.cumulative_shared_energy,
            "cumulative_provider_export": self.cumulative_provider_export,
            "cumulative_expected_shared": self.cumulative_expected_shared,
            "cumulative_used": self.cumulative_used,
            "cumulative_unused": self.cumulative_unused,
            "cumulative_billable_energy": self.cumulative_billable_energy,
            "processed_intervals": self.processed_intervals,
            "skipped_intervals": self.skipped_intervals,
            "source_reset_count": self.source_reset_count,
            "invalid_reading_count": self.invalid_reading_count,
            "reconciliation_mismatch_count": self.reconciliation_mismatch_count,
            "last_failure": (
                self.last_failure.to_dict() if self.last_failure else None
            ),
            "last_source_reset": (
                self.last_source_reset.to_dict()
                if self.last_source_reset
                else None
            ),
            "active_load_estimated_power_w": dict(self.active_load_estimated_power_w),
            "ideal_share_history": list(self.ideal_share_history),
            "active_load_cumulative_mopped_up_wh": (
                self.active_load_cumulative_mopped_up_wh
            ),
            "active_load_cumulative_overshoot_wh": (
                self.active_load_cumulative_overshoot_wh
            ),
            "active_load_cumulative_undershoot_wh": (
                self.active_load_cumulative_undershoot_wh
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StorageData:
        """Deserialize from storage with migration support."""
        if not isinstance(data, dict):
            return cls()

        version = _safe_int(data.get("version", 1), 1)
        if version != STORAGE_VERSION:
            data = migrate_storage(data, version)

        previous_snapshot = data.get("previous_snapshot")
        last_interval = data.get("last_interval")
        last_failure = data.get("last_failure")
        last_source_reset = data.get("last_source_reset")

        return cls(
            version=STORAGE_VERSION,
            baseline_initialized=bool(data.get("baseline_initialized", False)),
            baseline_initialization_count=_safe_int(
                data.get("baseline_initialization_count", 0), 0
            ),
            previous_snapshot=(
                BoundarySnapshot.from_dict(previous_snapshot)
                if isinstance(previous_snapshot, dict)
                else None
            ),
            last_processed_interval_id=data.get("last_processed_interval_id"),
            last_interval=(
                IntervalResult.from_dict(last_interval)
                if isinstance(last_interval, dict)
                else None
            ),
            cumulative_receiver_import=_safe_float(
                data.get("cumulative_receiver_import", 0.0), 0.0
            ),
            cumulative_shared_energy=_safe_float(
                data.get("cumulative_shared_energy", 0.0), 0.0
            ),
            cumulative_provider_export=_safe_float(
                data.get("cumulative_provider_export", 0.0), 0.0
            ),
            cumulative_expected_shared=_safe_float(
                data.get("cumulative_expected_shared", 0.0), 0.0
            ),
            cumulative_used=_safe_float(data.get("cumulative_used", 0.0), 0.0),
            cumulative_unused=_safe_float(data.get("cumulative_unused", 0.0), 0.0),
            cumulative_billable_energy=_safe_float(
                data.get(
                    "cumulative_billable_energy",
                    data.get("cumulative_billable", 0.0),
                ),
                0.0,
            ),
            processed_intervals=_safe_int(data.get("processed_intervals", 0), 0),
            skipped_intervals=_safe_int(data.get("skipped_intervals", 0), 0),
            source_reset_count=_safe_int(data.get("source_reset_count", 0), 0),
            invalid_reading_count=_safe_int(data.get("invalid_reading_count", 0), 0),
            reconciliation_mismatch_count=_safe_int(
                data.get("reconciliation_mismatch_count", 0), 0
            ),
            last_failure=(
                FailureRecord.from_dict(last_failure)
                if isinstance(last_failure, dict)
                else None
            ),
            last_source_reset=(
                SourceResetRecord.from_dict(last_source_reset)
                if isinstance(last_source_reset, dict)
                else None
            ),
            active_load_estimated_power_w=_active_load_estimated_power_from_dict(
                data.get("active_load_estimated_power_w")
            ),
            ideal_share_history=_ideal_share_history_from_dict(
                data.get("ideal_share_history")
            ),
            active_load_cumulative_mopped_up_wh=_safe_float(
                data.get("active_load_cumulative_mopped_up_wh", 0.0), 0.0
            ),
            active_load_cumulative_overshoot_wh=_safe_float(
                data.get("active_load_cumulative_overshoot_wh", 0.0), 0.0
            ),
            active_load_cumulative_undershoot_wh=_safe_float(
                data.get("active_load_cumulative_undershoot_wh", 0.0), 0.0
            ),
        )


def _ideal_share_history_from_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    history: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        interval_end = item.get("interval_end")
        if not isinstance(interval_end, str):
            continue
        provider_export_kwh = item.get("provider_export_kwh")
        history.append(
            {
                "interval_end": interval_end,
                "receiver_import_kwh": _safe_float(
                    item.get("receiver_import_kwh", 0.0), 0.0
                ),
                "provider_export_kwh": (
                    _safe_float(provider_export_kwh, -1.0)
                    if provider_export_kwh is not None
                    else None
                ),
                "active_load_kwh": _safe_float(
                    item.get("active_load_kwh", 0.0), 0.0
                ),
            }
        )
    return history


def _active_load_estimated_power_from_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    estimates: dict[str, float] = {}
    for entity_id, power in value.items():
        if not isinstance(entity_id, str):
            continue
        power_w = _safe_float(power, -1.0)
        if power_w > 0:
            estimates[entity_id] = power_w
    return estimates


def migrate_storage(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate storage data to the current schema version."""
    migrated = dict(data)

    if from_version < 2:
        migrated["cumulative_receiver_import"] = migrated.pop(
            "cumulative_imported", 0.0
        )
        migrated["cumulative_shared_energy"] = migrated.pop(
            "cumulative_shared", migrated.pop("cumulative_calculated_allocated", 0.0)
        )

    if from_version < 3:
        migrated["baseline_initialized"] = False
        migrated["baseline_initialization_count"] = 0
        migrated["previous_snapshot"] = None
        migrated["last_processed_interval_id"] = None
        migrated["last_interval"] = None
        migrated["cumulative_expected_shared"] = 0.0
        migrated["source_reset_count"] = 0
        migrated["invalid_reading_count"] = 0
        migrated["last_failure"] = None
        migrated["last_source_reset"] = None
        migrated["version"] = 3

    if from_version < 4:
        if migrated.get("cumulative_billable") is not None:
            migrated["cumulative_billable_energy"] = migrated.pop("cumulative_billable")
        elif migrated.get("cumulative_billable_energy") is None:
            migrated["cumulative_billable_energy"] = 0.0
        last_interval = migrated.get("last_interval")
        if isinstance(last_interval, dict) and "billable_grid_kwh" in last_interval:
            last_interval["billable_energy_kwh"] = last_interval.pop(
                "billable_grid_kwh"
            )

    if from_version < 5:
        migrated.setdefault("active_load_estimated_power_w", {})

    if from_version < 6:
        migrated.setdefault("ideal_share_history", [])

    if from_version < 7:
        migrated.setdefault("active_load_cumulative_mopped_up_wh", 0.0)
        migrated.setdefault("active_load_cumulative_overshoot_wh", 0.0)
        migrated.setdefault("active_load_cumulative_undershoot_wh", 0.0)

    migrated["version"] = STORAGE_VERSION
    return migrated


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value to the given range."""
    return max(minimum, min(value, maximum))


def calculate_ideal_share_excluding_active_loads_pct(
    *,
    imported_kwh: float,
    provider_export_kwh: float | None,
    active_load_kwh: float,
) -> float | None:
    """Calculate ideal share from organic receiver import excluding ACL mop-up."""
    if not is_ideal_share_stats_eligible(provider_export_kwh):
        return None
    assert provider_export_kwh is not None
    organic_import_kwh = max(imported_kwh - active_load_kwh, 0.0)
    return clamp(100.0 * organic_import_kwh / provider_export_kwh, 0.0, 100.0)


def is_ideal_share_stats_eligible(provider_export_kwh: float | None) -> bool:
    """Return True when an interval has measurable provider export (non-dark)."""
    return provider_export_kwh is not None and provider_export_kwh > 0


def append_ideal_share_history_sample(
    history: list[dict[str, Any]],
    *,
    interval_end: datetime,
    receiver_import_kwh: float,
    provider_export_kwh: float | None,
    active_load_kwh: float,
    retention_days: int = 7,
) -> None:
    """Append one interval sample and prune samples older than retention."""
    history.append(
        {
            "interval_end": interval_end.isoformat(),
            "receiver_import_kwh": receiver_import_kwh,
            "provider_export_kwh": provider_export_kwh,
            "active_load_kwh": active_load_kwh,
        }
    )
    cutoff = dt_util.as_utc(interval_end) - timedelta(days=retention_days)
    history[:] = [
        sample
        for sample in history
        if (
            parsed := dt_util.parse_datetime(sample.get("interval_end", ""))
        )
        is not None
        and dt_util.as_utc(parsed) >= cutoff
    ]


def compute_ideal_share_window_average(
    history: list[dict[str, Any]],
    *,
    window_hours: int,
    now: datetime | None = None,
) -> dict[str, float | int | None]:
    """Compute energy-weighted ideal share averages over a rolling window."""
    current = dt_util.as_utc(now or dt_util.utcnow())
    cutoff = current - timedelta(hours=window_hours)
    total_import_kwh = 0.0
    total_export_kwh = 0.0
    total_active_load_kwh = 0.0
    sample_count = 0
    excluded_dark_sample_count = 0

    for sample in history:
        interval_end = dt_util.parse_datetime(sample.get("interval_end", ""))
        if interval_end is None or dt_util.as_utc(interval_end) < cutoff:
            continue
        provider_export_kwh = sample.get("provider_export_kwh")
        export_kwh = (
            _safe_float(provider_export_kwh, -1.0)
            if provider_export_kwh is not None
            else None
        )
        if not is_ideal_share_stats_eligible(export_kwh):
            excluded_dark_sample_count += 1
            continue
        assert export_kwh is not None
        total_import_kwh += _safe_float(sample.get("receiver_import_kwh", 0.0), 0.0)
        total_export_kwh += export_kwh
        total_active_load_kwh += _safe_float(sample.get("active_load_kwh", 0.0), 0.0)
        sample_count += 1

    if sample_count == 0 or total_export_kwh <= 0:
        return {
            "ideal_share_pct": None,
            "ideal_share_excluding_active_loads_pct": None,
            "sample_count": 0,
            "excluded_dark_sample_count": excluded_dark_sample_count,
        }

    organic_import_kwh = max(total_import_kwh - total_active_load_kwh, 0.0)
    return {
        "ideal_share_pct": clamp(
            100.0 * total_import_kwh / total_export_kwh, 0.0, 100.0
        ),
        "ideal_share_excluding_active_loads_pct": clamp(
            100.0 * organic_import_kwh / total_export_kwh, 0.0, 100.0
        ),
        "sample_count": sample_count,
        "excluded_dark_sample_count": excluded_dark_sample_count,
    }


def resolve_operating_mode(
    has_provider_export: bool, has_fixed_percentage: bool
) -> str:
    """Resolve the operating mode from configured inputs."""
    if has_provider_export and has_fixed_percentage:
        return MODE_EXPORT_AND_PERCENTAGE
    if has_provider_export:
        return MODE_EXPORT_ONLY
    return MODE_PERCENTAGE_ONLY


def calculate_interval_delta(
    current_total: float, previous_total: float
) -> tuple[float | None, bool]:
    """Calculate interval delta or detect counter reset.

    Returns (delta_kwh, is_reset).
    """
    if current_total >= previous_total:
        return current_total - previous_total, False
    return None, True


def calculate_settlement(
    *,
    operating_mode: str,
    imported: float,
    shared: float,
    provider_export: float | None,
    fixed_percentage: float | None,
) -> dict[str, float | str | None]:
    """Calculate settlement values for one interval."""
    used_shared_kwh = min(shared, imported)
    unused_shared_kwh = max(shared - imported, 0.0)
    billable_energy_kwh = max(imported - shared, 0.0)

    allocation_utilization_pct: float | None = None
    if shared > 0:
        allocation_utilization_pct = 100.0 * used_shared_kwh / shared

    consumption_coverage_pct: float | None = None
    if imported > 0:
        consumption_coverage_pct = 100.0 * used_shared_kwh / imported

    provider_export_interval_kwh: float | None = provider_export
    provider_export_source_type = EXPORT_TYPE_NONE
    expected_shared_kwh: float | None = None
    effective_allocation_pct: float | None = None
    required_share_pct: float | None = None
    ideal_share_pct: float | None = None
    allocation_difference_kwh: float | None = None
    allocation_difference_pct: float | None = None

    if operating_mode == MODE_PERCENTAGE_ONLY:
        assert fixed_percentage is not None and fixed_percentage > 0
        provider_export_interval_kwh = shared / (fixed_percentage / 100.0)
        provider_export_source_type = EXPORT_TYPE_INFERRED
        if provider_export_interval_kwh > 0:
            required_share_pct = 100.0 * imported / provider_export_interval_kwh
            ideal_share_pct = clamp(required_share_pct, 0.0, 100.0)

    elif operating_mode == MODE_EXPORT_ONLY:
        assert provider_export is not None
        provider_export_source_type = EXPORT_TYPE_MEASURED
        if provider_export > 0:
            effective_allocation_pct = 100.0 * shared / provider_export
            required_share_pct = 100.0 * imported / provider_export
            ideal_share_pct = clamp(required_share_pct, 0.0, 100.0)

    elif operating_mode == MODE_EXPORT_AND_PERCENTAGE:
        assert provider_export is not None and fixed_percentage is not None
        provider_export_source_type = EXPORT_TYPE_MEASURED
        expected_shared_kwh = provider_export * fixed_percentage / 100.0
        allocation_difference_kwh = shared - expected_shared_kwh
        if expected_shared_kwh > 0:
            allocation_difference_pct = (
                100.0 * abs(allocation_difference_kwh) / expected_shared_kwh
            )
        if provider_export > 0:
            effective_allocation_pct = 100.0 * shared / provider_export
            required_share_pct = 100.0 * imported / provider_export
            ideal_share_pct = clamp(required_share_pct, 0.0, 100.0)

    return {
        "used_shared_kwh": used_shared_kwh,
        "unused_shared_kwh": unused_shared_kwh,
        "billable_energy_kwh": billable_energy_kwh,
        "allocation_utilization_pct": allocation_utilization_pct,
        "consumption_coverage_pct": consumption_coverage_pct,
        "provider_export_interval_kwh": provider_export_interval_kwh,
        "provider_export_source_type": provider_export_source_type,
        "expected_shared_kwh": expected_shared_kwh,
        "effective_allocation_pct": effective_allocation_pct,
        "required_share_pct": required_share_pct,
        "ideal_share_pct": ideal_share_pct,
        "allocation_difference_kwh": allocation_difference_kwh,
        "allocation_difference_pct": allocation_difference_pct,
    }


def evaluate_reconciliation(
    expected_shared_kwh: float,
    actual_shared_kwh: float,
    tolerance_kwh: float,
    tolerance_pct: float,
) -> dict[str, float | bool]:
    """Evaluate reconciliation in export-and-percentage mode.

    Reconciliation passes when either:
    - abs(actual - expected) <= tolerance_kwh, OR
    - allocation_difference_pct <= tolerance_pct
    """
    difference_kwh = actual_shared_kwh - expected_shared_kwh
    difference_pct: float | None = None
    if expected_shared_kwh > 0:
        difference_pct = 100.0 * abs(difference_kwh) / expected_shared_kwh

    within_kwh = abs(difference_kwh) <= tolerance_kwh
    within_pct = difference_pct is not None and difference_pct <= tolerance_pct
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
