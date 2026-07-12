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
    CONF_REPORTED_ALLOCATION_SOURCE,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    STATUS_READY,
    STATUS_RECONCILIATION_MISMATCH,
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
    reconciliation_only: bool = False
    interval_start: bool = False


INTERVAL_KWH_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
    EnergySharingSensorDescription(
        key="provider_export_last_interval",
        translation_key="provider_export_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-export-outline",
        value_key="provider_exported_kwh",
    ),
    EnergySharingSensorDescription(
        key="receiver_import_last_interval",
        translation_key="receiver_import_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-import",
        value_key="receiver_imported_kwh",
    ),
    EnergySharingSensorDescription(
        key="calculated_allocated_last_interval",
        translation_key="calculated_allocated_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_key="calculated_allocated_kwh",
    ),
    EnergySharingSensorDescription(
        key="reported_allocated_last_interval",
        translation_key="reported_allocated_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
        value_key="reported_allocated_kwh",
        reconciliation_only=True,
    ),
    EnergySharingSensorDescription(
        key="allocation_difference_last_interval",
        translation_key="allocation_difference_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compare-horizontal",
        value_key="allocation_difference_kwh",
        reconciliation_only=True,
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
        key="billable_grid_last_interval",
        translation_key="billable_grid_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        value_key="billable_grid_kwh",
    ),
)

INTERVAL_PERCENT_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
    EnergySharingSensorDescription(
        key="effective_allocation_percentage_last_interval",
        translation_key="effective_allocation_percentage_last_interval",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_key="allocation_percentage",
        percentage=True,
    ),
    EnergySharingSensorDescription(
        key="allocation_difference_pct_last_interval",
        translation_key="allocation_difference_pct_last_interval",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent-outline",
        value_key="allocation_difference_pct",
        percentage=True,
        reconciliation_only=True,
    ),
    EnergySharingSensorDescription(
        key="required_share_last_interval",
        translation_key="required_share_last_interval",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_key="required_share_pct",
        percentage=True,
    ),
    EnergySharingSensorDescription(
        key="ideal_share_last_interval",
        translation_key="ideal_share_last_interval",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent-outline",
        value_key="ideal_share_pct",
        percentage=True,
    ),
    EnergySharingSensorDescription(
        key="allocation_utilization_last_interval",
        translation_key="allocation_utilization_last_interval",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-donut",
        value_key="allocation_utilization_pct",
        percentage=True,
    ),
    EnergySharingSensorDescription(
        key="consumption_coverage_last_interval",
        translation_key="consumption_coverage_last_interval",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-arc",
        value_key="consumption_coverage_pct",
        percentage=True,
    ),
)

CUMULATIVE_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
    EnergySharingSensorDescription(
        key="total_provider_export",
        translation_key="total_provider_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:home-export-outline",
        value_key="cumulative_provider_export",
        cumulative=True,
    ),
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
        key="total_calculated_allocated",
        translation_key="total_calculated_allocated",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        value_key="cumulative_calculated_allocated",
        cumulative=True,
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
        key="total_billable_grid",
        translation_key="total_billable_grid",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:cash",
        value_key="cumulative_billable",
        cumulative=True,
    ),
)

STATUS_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
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
        key="last_processed_interval",
        translation_key="last_processed_interval",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        timestamp=True,
    ),
    EnergySharingSensorDescription(
        key="reconciliation_status",
        translation_key="reconciliation_status",
        icon="mdi:compare",
        status=True,
        value_key="reconciliation_status",
    ),
    EnergySharingSensorDescription(
        key="integration_status",
        translation_key="integration_status",
        icon="mdi:state-machine",
        status=True,
    ),
    EnergySharingSensorDescription(
        key="last_skip_reason",
        translation_key="last_skip_reason",
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
        key="reconciliation_mismatch_count",
        translation_key="reconciliation_mismatch_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_key="reconciliation_mismatch_count",
        counter=True,
    ),
    EnergySharingSensorDescription(
        key="current_allocation_percentage",
        translation_key="current_allocation_percentage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        percentage=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergySharingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Sharing sensors."""
    manager = entry.runtime_data.manager
    has_reconciliation = bool(entry.options.get(CONF_REPORTED_ALLOCATION_SOURCE))
    entities: list[EnergySharingSensor] = []

    for description in (
        *INTERVAL_KWH_SENSORS,
        *INTERVAL_PERCENT_SENSORS,
        *CUMULATIVE_SENSORS,
        *STATUS_SENSORS,
    ):
        if description.reconciliation_only and not has_reconciliation:
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
        """Initialize the sensor."""
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
        """Subscribe to manager updates."""
        self._unsub_update = self._manager.add_update_listener(
            self._handle_manager_update
        )
        self._update_from_manager()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from manager updates."""
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None

    @callback
    def _handle_manager_update(self) -> None:
        """Handle manager data updates."""
        self._update_from_manager()
        self.async_write_ha_state()

    @callback
    def _update_from_manager(self) -> None:
        """Update sensor state from manager data."""
        description = self.entity_description
        data = self._manager.data
        last_interval = data.last_interval

        if description.key == "integration_status":
            self._attr_native_value = self._manager.status
            self._attr_available = True
            return

        if description.key == "last_skip_reason":
            self._attr_native_value = (
                data.last_skip.reason if data.last_skip else None
            )
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

        if description.key == "current_allocation_percentage":
            self._attr_native_value = self._manager.get_effective_percentage()
            self._attr_available = self._attr_native_value is not None
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
            key = description.value_key
            assert key is not None
            self._attr_native_value = getattr(data, key)
            self._attr_available = True
            return

        if last_interval is None:
            self._attr_native_value = None
            self._attr_available = False
            self._attr_extra_state_attributes = {
                "validity": "no_interval_processed",
                "status": self._manager.status,
            }
            return

        key = description.value_key
        assert key is not None
        self._attr_native_value = getattr(last_interval, key)
        self._attr_available = self._manager.status in (
            STATUS_READY,
            STATUS_RECONCILIATION_MISMATCH,
        ) or (self._attr_native_value is not None)
        self._attr_extra_state_attributes = _interval_attributes(last_interval)

    @property
    def available(self) -> bool:
        """Return availability based on processed data."""
        if hasattr(self, "_attr_available"):
            return self._attr_available
        return self._manager.data.last_interval is not None


def _interval_attributes(interval: IntervalResult) -> dict[str, Any]:
    """Build stable extra attributes for interval sensors."""
    return {
        "interval_id": interval.interval_id,
        "interval_start": interval.interval_start.isoformat(),
        "interval_end": interval.interval_end.isoformat(),
        "allocation_percentage": interval.allocation_percentage,
        "provider_export_source": interval.provider_export_source,
        "receiver_import_source": interval.receiver_import_source,
        "reported_allocation_source": interval.reported_allocation_source,
        "allocation_percentage_source": interval.allocation_percentage_source,
        "reconciliation_status": interval.reconciliation_status,
        "processed_at": interval.processed_at.isoformat(),
        "validity": "valid",
        "status": STATUS_READY,
    }
