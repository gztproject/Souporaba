"""Sensor platform for Energy Sharing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
from homeassistant.helpers.typing import StateType

from . import EnergySharingConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL, STATUS_READY
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


INTERVAL_KWH_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
    EnergySharingSensorDescription(
        key="imported_last_interval",
        translation_key="imported_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-import",
        value_key="imported_kwh",
    ),
    EnergySharingSensorDescription(
        key="shared_last_interval",
        translation_key="shared_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_key="shared_kwh",
    ),
    EnergySharingSensorDescription(
        key="exported_last_interval",
        translation_key="exported_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-export-outline",
        value_key="exported_kwh",
    ),
    EnergySharingSensorDescription(
        key="used_last_interval",
        translation_key="used_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:check-circle-outline",
        value_key="used_kwh",
    ),
    EnergySharingSensorDescription(
        key="unused_last_interval",
        translation_key="unused_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:close-circle-outline",
        value_key="unused_kwh",
    ),
    EnergySharingSensorDescription(
        key="billable_last_interval",
        translation_key="billable_last_interval",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        value_key="billable_kwh",
    ),
)

INTERVAL_PERCENT_SENSORS: tuple[EnergySharingSensorDescription, ...] = (
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
        key="total_imported",
        translation_key="total_imported",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:transmission-tower-import",
        value_key="cumulative_imported",
        cumulative=True,
    ),
    EnergySharingSensorDescription(
        key="total_shared",
        translation_key="total_shared",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        value_key="cumulative_shared",
        cumulative=True,
    ),
    EnergySharingSensorDescription(
        key="total_used",
        translation_key="total_used",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:check-circle-outline",
        value_key="cumulative_used",
        cumulative=True,
    ),
    EnergySharingSensorDescription(
        key="total_unused",
        translation_key="total_unused",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:close-circle-outline",
        value_key="cumulative_unused",
        cumulative=True,
    ),
    EnergySharingSensorDescription(
        key="total_billable",
        translation_key="total_billable",
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
        key="last_processed_interval",
        translation_key="last_processed_interval",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        timestamp=True,
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
        key="integration_status",
        translation_key="integration_status",
        icon="mdi:state-machine",
        status=True,
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
    entities: list[EnergySharingSensor] = []

    for description in (
        *INTERVAL_KWH_SENSORS,
        *INTERVAL_PERCENT_SENSORS,
        *CUMULATIVE_SENSORS,
        *STATUS_SENSORS,
    ):
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

        if description.status:
            self._attr_native_value = self._manager.status
            self._attr_extra_state_attributes = {
                "last_skip_reason": (
                    data.last_skip.reason if data.last_skip else None
                ),
            }
            return

        if description.key == "current_allocation_percentage":
            self._attr_native_value = self._manager.get_effective_percentage()
            self._attr_available = self._attr_native_value is not None
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
        self._attr_available = self._manager.status == STATUS_READY or (
            self._attr_native_value is not None
        )
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
        "grid_import_entity": interval.grid_import_entity,
        "shared_energy_entity": interval.shared_energy_entity,
        "processed_at": interval.processed_at.isoformat(),
        "validity": "valid",
        "status": STATUS_READY,
    }
