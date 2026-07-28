"""Sensor platform for Energy Sharing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EnergySharingConfigEntry
from .const import (
    DOMAIN,
    EXPORT_TYPE_INFERRED,
    EXPORT_TYPE_MEASURED,
    MANUFACTURER,
    MODE_EXPORT_AND_PERCENTAGE,
    MODEL,
)
from .manager import EnergySharingManager
from .models import IntervalResult

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EnergySharingSensorDescription(SensorEntityDescription):
    """Describe an Energy Sharing sensor."""

    value_key: str | None = None
    cumulative: bool = False
    percentage: bool = False
    status: bool = False
    timestamp: bool = False
    counter: bool = False
    interval_start: bool = False
    provider_only: bool = False
    export_and_percentage_only: bool = False
    fixed_percentage_only: bool = False


def _interval_energy_sensors() -> tuple[EnergySharingSensorDescription, ...]:
    return (
        EnergySharingSensorDescription(
            key="receiver_import_last_interval",
            translation_key="receiver_import_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:transmission-tower-import",
            value_key="receiver_import_interval_kwh",
        ),
        EnergySharingSensorDescription(
            key="shared_energy_last_interval",
            translation_key="shared_energy_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:solar-power",
            value_key="shared_energy_interval_kwh",
        ),
        EnergySharingSensorDescription(
            key="provider_export_last_interval",
            translation_key="provider_export_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:home-export-outline",
            value_key="provider_export_interval_kwh",
            provider_only=True,
        ),
        EnergySharingSensorDescription(
            key="expected_shared_last_interval",
            translation_key="expected_shared_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:solar-power-variant",
            value_key="expected_shared_kwh",
            export_and_percentage_only=True,
        ),
        EnergySharingSensorDescription(
            key="used_shared_last_interval",
            translation_key="used_shared_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:check-circle-outline",
            value_key="used_shared_kwh",
        ),
        EnergySharingSensorDescription(
            key="unused_shared_last_interval",
            translation_key="unused_shared_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:close-circle-outline",
            value_key="unused_shared_kwh",
        ),
        EnergySharingSensorDescription(
            key="billable_energy_last_interval",
            translation_key="billable_energy_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:cash",
            value_key="billable_energy_kwh",
        ),
        EnergySharingSensorDescription(
            key="allocation_difference_last_interval",
            translation_key="allocation_difference_last_interval",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:compare-horizontal",
            value_key="allocation_difference_kwh",
            export_and_percentage_only=True,
        ),
    )


def _interval_percent_sensors() -> tuple[EnergySharingSensorDescription, ...]:
    return (
        EnergySharingSensorDescription(
            key="fixed_allocation_percentage_last_interval",
            translation_key="fixed_allocation_percentage_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:percent",
            value_key="fixed_allocation_percentage",
            fixed_percentage_only=True,
        ),
        EnergySharingSensorDescription(
            key="effective_allocation_percentage_last_interval",
            translation_key="effective_allocation_percentage_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:percent-outline",
            value_key="effective_allocation_pct",
        ),
        EnergySharingSensorDescription(
            key="required_share_last_interval",
            translation_key="required_share_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:percent",
            value_key="required_share_pct",
        ),
        EnergySharingSensorDescription(
            key="ideal_share_last_interval",
            translation_key="ideal_share_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:percent-outline",
            value_key="ideal_share_pct",
        ),
        EnergySharingSensorDescription(
            key="allocation_utilization_last_interval",
            translation_key="allocation_utilization_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:chart-donut",
            value_key="allocation_utilization_pct",
        ),
        EnergySharingSensorDescription(
            key="consumption_coverage_last_interval",
            translation_key="consumption_coverage_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:chart-arc",
            value_key="consumption_coverage_pct",
        ),
        EnergySharingSensorDescription(
            key="allocation_difference_pct_last_interval",
            translation_key="allocation_difference_pct_last_interval",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:compare",
            value_key="allocation_difference_pct",
            export_and_percentage_only=True,
        ),
    )


def _cumulative_sensors() -> tuple[EnergySharingSensorDescription, ...]:
    return (
        EnergySharingSensorDescription(
            key="total_receiver_import",
            translation_key="total_receiver_import",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:transmission-tower-import",
            value_key="cumulative_receiver_import",
            cumulative=True,
        ),
        EnergySharingSensorDescription(
            key="total_shared_energy",
            translation_key="total_shared_energy",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:solar-power",
            value_key="cumulative_shared_energy",
            cumulative=True,
        ),
        EnergySharingSensorDescription(
            key="total_provider_export",
            translation_key="total_provider_export",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:home-export-outline",
            value_key="cumulative_provider_export",
            cumulative=True,
            provider_only=True,
        ),
        EnergySharingSensorDescription(
            key="total_expected_shared",
            translation_key="total_expected_shared",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:solar-power-variant",
            value_key="cumulative_expected_shared",
            cumulative=True,
            export_and_percentage_only=True,
        ),
        EnergySharingSensorDescription(
            key="total_used_shared",
            translation_key="total_used_shared",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:check-circle-outline",
            value_key="cumulative_used",
            cumulative=True,
        ),
        EnergySharingSensorDescription(
            key="total_unused_shared",
            translation_key="total_unused_shared",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:close-circle-outline",
            value_key="cumulative_unused",
            cumulative=True,
        ),
        EnergySharingSensorDescription(
            key="total_billable_energy",
            translation_key="total_billable_energy",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:cash",
            value_key="cumulative_billable_energy",
            cumulative=True,
        ),
    )


STATUS_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
    EnergySharingSensorDescription(
        key="processing_status",
        translation_key="processing_status",
        icon="mdi:state-machine",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="baseline_status",
        translation_key="baseline_status",
        icon="mdi:flag-checkered",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="interval_start",
        translation_key="interval_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        interval_start=True,
    ),
    EnergySharingSensorDescription(
        key="interval_end",
        translation_key="interval_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-end",
        timestamp=True,
    ),
    EnergySharingSensorDescription(
        key="last_processed_interval_id",
        translation_key="last_processed_interval_id",
        icon="mdi:identifier",
        status=True,
        value_key="last_processed_interval_id",
    ),
    EnergySharingSensorDescription(
        key="operating_mode",
        translation_key="operating_mode",
        icon="mdi:cog-outline",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="provider_export_source_type",
        translation_key="provider_export_source_type",
        icon="mdi:source-branch",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="reconciliation_status",
        translation_key="reconciliation_status",
        icon="mdi:compare",
        status=True,
        value_key="reconciliation_status",
    ),
    EnergySharingSensorDescription(
        key="last_failure_reason",
        translation_key="last_failure_reason",
        icon="mdi:alert-circle-outline",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="processed_interval_count",
        translation_key="processed_interval_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_key="processed_intervals",
        counter=True,
    ),
    EnergySharingSensorDescription(
        key="skipped_interval_count",
        translation_key="skipped_interval_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_key="skipped_intervals",
        counter=True,
    ),
    EnergySharingSensorDescription(
        key="source_reset_count",
        translation_key="source_reset_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_key="source_reset_count",
        counter=True,
    ),
    EnergySharingSensorDescription(
        key="reconciliation_mismatch_count",
        translation_key="reconciliation_mismatch_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_key="reconciliation_mismatch_count",
        counter=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_target_wh",
        translation_key="active_load_target_wh",
        icon="mdi:target",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_measured_wh",
        translation_key="active_load_measured_wh",
        icon="mdi:lightning-bolt",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_remaining_wh",
        translation_key="active_load_remaining_wh",
        icon="mdi:chart-timeline-variant",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_available_count",
        translation_key="active_load_available_count",
        icon="mdi:counter",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_seconds_remaining",
        translation_key="active_load_seconds_remaining",
        icon="mdi:timer-outline",
        status=True,
    ),
    # Beta diagnostics — remove or hide before stable release.
    EnergySharingSensorDescription(
        key="active_load_control_enabled",
        translation_key="active_load_control_enabled",
        icon="mdi:toggle-switch",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_calibration_status",
        translation_key="active_load_calibration_status",
        icon="mdi:tune-variant",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_estimated_load_count",
        translation_key="active_load_estimated_load_count",
        icon="mdi:counter",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_correction_wh",
        translation_key="active_load_correction_wh",
        icon="mdi:delta",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_tracking_error_wh",
        translation_key="active_load_tracking_error_wh",
        icon="mdi:chart-bell-curve",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="active_load_unused_shared_wh",
        translation_key="active_load_unused_shared_wh",
        icon="mdi:solar-power-variant-outline",
        status=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergySharingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    mode = manager.operating_mode
    has_measured_provider = manager.provider_export_total_source is not None
    has_export_and_pct = mode == MODE_EXPORT_AND_PERCENTAGE
    has_fixed_pct = manager.fixed_allocation_percentage is not None

    entities: list[EnergySharingSensor] = []
    for description in (
        *_interval_energy_sensors(),
        *_interval_percent_sensors(),
        *_cumulative_sensors(),
        *STATUS_SENSORS,
    ):
        if description.export_and_percentage_only and not has_export_and_pct:
            continue
        if description.fixed_percentage_only and not has_fixed_pct:
            continue
        if (
            description.key == "total_provider_export"
            and not has_measured_provider
        ):
            continue
        if (
            description.provider_only
            and description.key != "provider_export_last_interval"
        ):
            continue
        entities.append(EnergySharingSensor(entry, manager, description))

    async_add_entities(entities)


class EnergySharingSensor(SensorEntity):
    """Representation of an Energy Sharing sensor."""

    _attr_has_entity_name = True
    entity_description: EnergySharingSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        manager: EnergySharingManager,
        description: EnergySharingSensorDescription,
    ) -> None:
        self.entity_description = description
        self._entry = entry
        self._manager = manager
        self._unsub_update: Callable[[], None] | None = None
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=manager.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._attr_translation_key = description.translation_key

    async def async_added_to_hass(self) -> None:
        self._unsub_update = self._manager.add_update_listener(
            self._handle_manager_update
        )
        self._update_from_manager()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None

    @callback
    def _handle_manager_update(self) -> None:
        self._update_from_manager()
        self.async_write_ha_state()

    @callback
    def _update_from_manager(self) -> None:
        description = self.entity_description
        data = self._manager.data
        last_interval = data.last_interval

        if description.key == "processing_status":
            self._attr_native_value = self._manager.status
            self._attr_available = True
            return

        if description.key == "baseline_status":
            self._attr_native_value = self._manager.baseline_status
            self._attr_available = True
            return

        if description.key == "operating_mode":
            self._attr_native_value = self._manager.operating_mode
            self._attr_available = True
            return

        if description.key == "provider_export_source_type":
            if last_interval is None:
                self._attr_native_value = None
                self._attr_available = False
            else:
                self._attr_native_value = last_interval.provider_export_source_type
                self._attr_available = True
            return

        if description.key == "last_failure_reason":
            self._attr_native_value = (
                data.last_failure.reason if data.last_failure else None
            )
            self._attr_available = True
            return

        if description.key.startswith("active_load_"):
            active = self._manager.get_diagnostics_snapshot().get("active_loads") or {}
            if description.key == "active_load_control_enabled":
                if not active:
                    self._attr_native_value = None
                    self._attr_available = False
                else:
                    self._attr_native_value = (
                        "enabled" if active.get("control_enabled") else "disabled"
                    )
                    self._attr_available = True
                return
            if description.key == "active_load_calibration_status":
                if not active:
                    self._attr_native_value = None
                    self._attr_available = False
                else:
                    self._attr_native_value = (
                        "running" if active.get("calibration_in_progress") else "idle"
                    )
                    self._attr_available = True
                    self._attr_extra_state_attributes = {
                        "last_result": active.get("calibration_last_result"),
                        "last_finished_at": active.get("calibration_last_finished_at"),
                    }
                return
            value_map = {
                "active_load_target_wh": "target_wh",
                "active_load_measured_wh": "measured_wh",
                "active_load_remaining_wh": "remaining_wh",
                "active_load_available_count": "available_load_count",
                "active_load_seconds_remaining": "seconds_remaining",
                "active_load_estimated_load_count": "estimated_load_count",
                "active_load_correction_wh": "applied_correction_wh",
                "active_load_tracking_error_wh": "tracking_error_wh",
                "active_load_unused_shared_wh": "last_unused_shared_wh",
            }
            key = value_map.get(description.key)
            if key is None:
                return
            self._attr_native_value = active.get(key)
            self._attr_available = active != {}
            if active:
                self._attr_extra_state_attributes = {
                    "loads": active.get("loads", []),
                    "interval_id": active.get("interval_id"),
                    "configured_load_count": active.get("configured_load_count"),
                    "calibration_in_progress": active.get("calibration_in_progress"),
                }
            return

        if description.key == "last_processed_interval_id":
            self._attr_native_value = data.last_processed_interval_id
            self._attr_available = True
            return

        if description.key == "reconciliation_status":
            if last_interval is None:
                self._attr_native_value = None
                self._attr_available = False
            else:
                self._attr_native_value = last_interval.reconciliation_status
                self._attr_available = True
            return

        if description.interval_start:
            if last_interval is None:
                self._attr_native_value = None
                self._attr_available = False
            else:
                self._attr_native_value = last_interval.interval_start
                self._attr_available = True
            return

        if description.timestamp:
            if last_interval is None:
                self._attr_native_value = None
                self._attr_available = False
            else:
                self._attr_native_value = last_interval.interval_end
                self._attr_available = True
            return

        if description.cumulative or description.counter:
            value_key = description.value_key or ""
            self._attr_native_value = getattr(data, value_key)
            self._attr_available = True
            return

        if last_interval is None:
            self._attr_native_value = None
            self._attr_available = False
            return

        value_key = description.value_key or ""
        self._attr_native_value = getattr(last_interval, value_key)
        self._attr_available = last_interval.settlement_accumulated or (
            self._attr_native_value is not None
        )
        self._attr_extra_state_attributes = _interval_attributes(last_interval)

    @property
    def available(self) -> bool:
        if hasattr(self, "_attr_available"):
            return self._attr_available
        return self._manager.data.last_interval is not None


def _interval_attributes(interval: IntervalResult) -> dict[str, Any]:
    source_type = interval.provider_export_source_type
    if source_type == EXPORT_TYPE_MEASURED:
        export_attr = "measured"
    elif source_type == EXPORT_TYPE_INFERRED:
        export_attr = "inferred"
    else:
        export_attr = None

    attrs: dict[str, Any] = {
        "interval_id": interval.interval_id,
        "interval_start": interval.interval_start.isoformat(),
        "interval_end": interval.interval_end.isoformat(),
        "operating_mode": interval.operating_mode,
        "settlement_accumulated": interval.settlement_accumulated,
        "processed_at": interval.processed_at.isoformat(),
    }
    if export_attr and interval.provider_export_interval_kwh is not None:
        attrs["source_type"] = export_attr
    return attrs
