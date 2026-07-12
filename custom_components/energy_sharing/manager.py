"""Settlement manager for Energy Sharing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_LAST_RESET,
    CONF_ALLOW_PERCENTAGE_ABOVE_100,
    CONF_FIXED_PERCENTAGE,
    CONF_GRID_IMPORT_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PERCENTAGE_ENTITY,
    CONF_PERCENTAGE_MODE,
    CONF_PROCESSING_DELAY,
    CONF_RESET_TOLERANCE,
    CONF_RETRY_INTERVAL,
    CONF_SHARED_ENERGY_ENTITY,
    DEFAULT_FIXED_PERCENTAGE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RESET_TOLERANCE,
    DEFAULT_RETRY_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PERCENTAGE_MODE_ENTITY,
    PERCENTAGE_MODE_FIXED,
    SERVICE_CONFIRM,
    SERVICE_PROCESS_NOW,
    SERVICE_RESET_TOTALS,
    STATUS_INPUTS_UNAVAILABLE,
    STATUS_INPUTS_UNSYNCHRONIZED,
    STATUS_INVALID_INPUT,
    STATUS_PERCENTAGE_INVALID,
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_WAITING,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .helpers import (
    count_missed_intervals,
    get_expected_interval_end,
    interval_id_from_end,
    interval_start_from_end,
    parse_reset_timestamp,
    read_percentage,
    read_utility_meter_last_period_kwh,
    reset_matches_interval_end,
    resets_match,
)
from .models import (
    IntervalResult,
    SkipRecord,
    StorageData,
    calculate_interval,
)

if TYPE_CHECKING:
    from . import EnergySharingConfigEntry

_LOGGER = logging.getLogger(__name__)


class EnergySharingManager:
    """Manage interval settlement, persistence, and scheduling."""

    def __init__(self, hass: HomeAssistant, entry: EnergySharingConfigEntry) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.entry = entry
        self.storage = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry.entry_id}",
        )
        self.data = StorageData()
        self.status = STATUS_WAITING
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsub_schedule: CALLBACK_TYPE | None = None
        self._retry_unsub: CALLBACK_TYPE | None = None
        self._processing_lock = asyncio.Lock()
        self._retry_deadline: datetime | None = None
        self._retry_warning_logged = False
        self._entity_update_callbacks: list[CALLBACK_TYPE] = []
        self._update_listeners: list[Callable[[], None]] = []

    @property
    def device_name(self) -> str:
        """Return the device name."""
        return self.entry.title

    def get_option(self, key: str, default: Any = None) -> Any:
        """Read an option with fallback to default."""
        return self.entry.options.get(key, default)

    @property
    def interval_minutes(self) -> int:
        """Return configured interval length."""
        return int(self.get_option(CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES))

    @property
    def processing_delay(self) -> int:
        """Return configured processing delay."""
        return int(self.get_option(CONF_PROCESSING_DELAY, DEFAULT_PROCESSING_DELAY))

    @property
    def max_wait(self) -> int:
        """Return configured maximum wait."""
        return int(self.get_option(CONF_MAX_WAIT, DEFAULT_MAX_WAIT))

    @property
    def retry_interval(self) -> int:
        """Return configured retry interval."""
        return int(self.get_option(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL))

    @property
    def reset_tolerance(self) -> int:
        """Return configured reset tolerance."""
        return int(self.get_option(CONF_RESET_TOLERANCE, DEFAULT_RESET_TOLERANCE))

    @property
    def allow_percentage_above_100(self) -> bool:
        """Return whether percentages above 100 are allowed."""
        return bool(
            self.get_option(CONF_ALLOW_PERCENTAGE_ABOVE_100, False)
        )

    def add_update_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener for data updates."""
        self._update_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._update_listeners:
                self._update_listeners.remove(listener)

        return remove_listener

    @callback
    def _notify_update(self) -> None:
        """Notify listeners that data changed."""
        for listener in list(self._update_listeners):
            listener()

    async def async_setup(self) -> None:
        """Set up storage, device, services, and scheduler."""
        stored = await self.storage.async_load()
        if stored is not None:
            self.data = StorageData.from_dict(stored)

        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

        self._register_services()
        self._subscribe_source_entities()
        self._schedule_next_processing()
        self.status = STATUS_WAITING
        self._notify_update()

    async def async_unload(self) -> None:
        """Cancel timers and listeners."""
        self._cancel_retry()
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        for unsub in self._entity_update_callbacks:
            unsub()
        self._entity_update_callbacks.clear()

    def _register_services(self) -> None:
        """Register integration services once."""
        if self.hass.services.has_service(DOMAIN, SERVICE_PROCESS_NOW):
            return

        async def process_now_service(call: Any) -> None:
            entry = await self._resolve_entry_from_service(call)
            if entry is None:
                raise HomeAssistantError("config_entry_not_found")
            manager = entry.runtime_data.manager
            result = await manager.async_process_now()
            _LOGGER.info("process_now result for %s: %s", entry.title, result)

        async def reset_totals_service(call: Any) -> None:
            if not call.data.get(SERVICE_CONFIRM):
                raise HomeAssistantError("confirmation_required")
            entry = await self._resolve_entry_from_service(call)
            if entry is None:
                raise HomeAssistantError("config_entry_not_found")
            manager = entry.runtime_data.manager
            await manager.async_reset_totals()
            _LOGGER.info("Cumulative totals reset for %s", entry.title)

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_PROCESS_NOW,
            process_now_service,
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_TOTALS,
            reset_totals_service,
        )

    async def _resolve_entry_from_service(
        self, call: Any
    ) -> EnergySharingConfigEntry | None:
        """Resolve a config entry from a service call target."""
        device_ids: list[str] | None = None
        if call.target:
            device_ids = call.target.get("device_id")
        if not device_ids:
            return self.entry

        device_registry = dr.async_get(self.hass)
        for device_id in device_ids:
            device = device_registry.async_get(device_id)
            if device is None:
                continue
            for entry_id in device.config_entries:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN:
                    return entry
        return None

    def _subscribe_source_entities(self) -> None:
        """Subscribe to source entity updates to help retries."""
        entity_ids = [
            self.entry.data[CONF_GRID_IMPORT_ENTITY],
            self.entry.data[CONF_SHARED_ENERGY_ENTITY],
        ]
        if self.entry.data.get(CONF_PERCENTAGE_MODE) == PERCENTAGE_MODE_ENTITY:
            percentage_entity = self.entry.data.get(CONF_PERCENTAGE_ENTITY)
            if percentage_entity:
                entity_ids.append(percentage_entity)

        @callback
        def _source_changed(event: Any) -> None:
            if self._retry_deadline is not None:
                self.hass.async_create_task(self._async_retry_processing())

        for entity_id in entity_ids:
            self._entity_update_callbacks.append(
                async_track_state_change_event(
                    self.hass, entity_id, _source_changed
                )
            )

    def _schedule_next_processing(self) -> None:
        """Schedule processing at the next interval boundary plus delay."""
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None

        next_run = self._calculate_next_run(dt_util.now())
        _LOGGER.debug(
            "Scheduling next processing for %s at %s",
            self.entry.title,
            next_run,
        )
        self._unsub_schedule = async_track_point_in_time(
            self.hass,
            self._async_scheduled_processing,
            next_run,
        )

    def _calculate_next_run(self, now: datetime) -> datetime:
        """Calculate the next scheduled processing time."""
        local_now = dt_util.as_local(now)
        interval = self.interval_minutes
        delay = self.processing_delay

        minute = ((local_now.minute // interval) + 1) * interval
        hour = local_now.hour
        if minute >= 60:
            minute = 0
            hour += 1
            if hour >= 24:
                next_day = local_now + timedelta(days=1)
                return next_day.replace(
                    hour=0, minute=0, second=delay, microsecond=0
                )

        next_boundary = local_now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return dt_util.as_utc(next_boundary + timedelta(seconds=delay))

    @callback
    def _async_scheduled_processing(self, _now: datetime) -> None:
        """Handle scheduled processing."""
        self.hass.async_create_task(self._async_process_latest("scheduled"))
        self._schedule_next_processing()

    def _cancel_retry(self) -> None:
        """Cancel any pending retry timer."""
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    async def _async_retry_processing(self) -> None:
        """Retry processing while within the maximum wait window."""
        if self._retry_deadline is None:
            return
        if dt_util.utcnow() >= self._retry_deadline:
            return
        await self._async_process_latest("retry")

    async def async_process_now(self) -> str:
        """Public entry point for manual processing."""
        return await self._async_process_latest("manual")

    async def _async_process_latest(self, trigger: str) -> str:
        """Attempt to process the latest completed interval."""
        async with self._processing_lock:
            previous_status = self.status
            self.status = STATUS_PROCESSING
            self._notify_update()

            try:
                return await self._async_attempt_processing(trigger)
            finally:
                if self.status == STATUS_PROCESSING:
                    self.status = (
                        STATUS_READY
                        if self.data.last_interval is not None
                        else previous_status
                    )
                self._notify_update()

    async def _async_attempt_processing(self, trigger: str) -> str:
        """Core processing attempt with retry support."""
        now = dt_util.now()
        expected_end = get_expected_interval_end(now, self.interval_minutes)
        expected_interval_id = interval_id_from_end(expected_end)

        if self._retry_deadline is None:
            self._retry_deadline = now + timedelta(seconds=self.max_wait)
            self._retry_warning_logged = False

        try:
            inputs = await self._async_read_synchronized_inputs(expected_end)
        except _InputsUnavailableError:
            self.status = STATUS_INPUTS_UNAVAILABLE
            return await self._async_handle_retry(
                trigger,
                expected_interval_id,
                "inputs_unavailable",
            )
        except _InputsUnsynchronizedError as err:
            self.status = STATUS_INPUTS_UNSYNCHRONIZED
            return await self._async_handle_retry(
                trigger,
                expected_interval_id,
                err.reason,
            )
        except _InvalidInputError as err:
            self._clear_retry_state()
            self.status = STATUS_INVALID_INPUT
            await self._async_record_skip(err.reason, inputs.interval_id)
            return f"skipped:{err.reason}"

        try:
            percentage = await self._async_read_percentage()
        except _PercentageInvalidError as err:
            self._clear_retry_state()
            self.status = STATUS_PERCENTAGE_INVALID
            await self._async_record_skip(err.reason, inputs.interval_id)
            return f"skipped:{err.reason}"

        if percentage <= 0:
            self._clear_retry_state()
            self.status = STATUS_PERCENTAGE_INVALID
            await self._async_record_skip("percentage_zero", inputs.interval_id)
            return "skipped:percentage_zero"

        if percentage > 100 and not self.allow_percentage_above_100:
            self._clear_retry_state()
            self.status = STATUS_PERCENTAGE_INVALID
            await self._async_record_skip("percentage_above_100", inputs.interval_id)
            return "skipped:percentage_above_100"

        if (
            self.data.last_processed_interval_id is not None
            and inputs.interval_id == self.data.last_processed_interval_id
        ):
            self._clear_retry_state()
            self.status = STATUS_READY
            return "duplicate"

        if (
            self.data.last_processed_interval_id is not None
            and inputs.interval_id < self.data.last_processed_interval_id
        ):
            self._clear_retry_state()
            self.status = STATUS_READY
            return "stale"

        missed = count_missed_intervals(
            self.data.last_processed_interval_id,
            inputs.interval_id,
            self.interval_minutes,
        )

        calculations = calculate_interval(
            inputs.imported_kwh,
            inputs.shared_kwh,
            percentage,
        )

        interval_start = interval_start_from_end(
            inputs.interval_end, self.interval_minutes
        )
        result = IntervalResult(
            interval_id=inputs.interval_id,
            interval_start=interval_start,
            interval_end=inputs.interval_end,
            imported_kwh=inputs.imported_kwh,
            shared_kwh=inputs.shared_kwh,
            exported_kwh=calculations["exported_kwh"],
            used_kwh=float(calculations["used_kwh"]),
            unused_kwh=float(calculations["unused_kwh"]),
            billable_kwh=float(calculations["billable_kwh"]),
            required_share_pct=calculations["required_share_pct"],
            ideal_share_pct=calculations["ideal_share_pct"],
            allocation_utilization_pct=calculations["allocation_utilization_pct"],
            consumption_coverage_pct=calculations["consumption_coverage_pct"],
            allocation_percentage=percentage,
            grid_import_entity=self.entry.data[CONF_GRID_IMPORT_ENTITY],
            shared_energy_entity=self.entry.data[CONF_SHARED_ENERGY_ENTITY],
            processed_at=dt_util.utcnow(),
        )

        self.data.cumulative_imported += result.imported_kwh
        self.data.cumulative_shared += result.shared_kwh
        self.data.cumulative_used += result.used_kwh
        self.data.cumulative_unused += result.unused_kwh
        self.data.cumulative_billable += result.billable_kwh
        self.data.processed_intervals += 1
        if missed > 0:
            self.data.skipped_intervals += missed
            self.data.last_skip = SkipRecord(
                timestamp=dt_util.utcnow(),
                reason=f"missed_intervals:{missed}",
                interval_id=inputs.interval_id,
            )
        self.data.last_processed_interval_id = inputs.interval_id
        self.data.last_interval = result

        await self.storage.async_save(self.data.to_dict())

        self._clear_retry_state()
        self.status = STATUS_READY
        self._notify_update()

        _LOGGER.info(
            "Processed interval %s for %s via %s",
            inputs.interval_id,
            self.entry.title,
            trigger,
        )
        return "processed"

    async def _async_handle_retry(
        self,
        trigger: str,
        expected_interval_id: str,
        reason: str,
    ) -> str:
        """Handle retry or final skip when inputs are not ready."""
        now = dt_util.utcnow()
        if self._retry_deadline is not None and now < self._retry_deadline:
            if not self._retry_warning_logged:
                _LOGGER.warning(
                    "Inputs not ready for %s (%s), retrying until %s",
                    self.entry.title,
                    reason,
                    self._retry_deadline,
                )
                self._retry_warning_logged = True
            self._schedule_retry()
            return f"retrying:{reason}"

        self._clear_retry_state()
        await self._async_record_skip(reason, expected_interval_id)
        return f"skipped:{reason}"

    def _schedule_retry(self) -> None:
        """Schedule a retry attempt."""
        self._cancel_retry()

        @callback
        def _retry(_now: datetime) -> None:
            self.hass.async_create_task(self._async_retry_processing())

        self._retry_unsub = async_call_later(
            self.hass,
            self.retry_interval,
            _retry,
        )

    def _clear_retry_state(self) -> None:
        """Clear retry tracking state."""
        self._cancel_retry()
        self._retry_deadline = None
        self._retry_warning_logged = False

    async def _async_record_skip(
        self, reason: str, interval_id: str | None
    ) -> None:
        """Record a skipped interval."""
        self.data.skipped_intervals += 1
        self.data.last_skip = SkipRecord(
            timestamp=dt_util.utcnow(),
            reason=reason,
            interval_id=interval_id,
        )
        await self.storage.async_save(self.data.to_dict())
        self._notify_update()
        _LOGGER.warning(
            "Skipped interval for %s: %s (%s)",
            self.entry.title,
            reason,
            interval_id,
        )

    async def _async_read_percentage(self) -> float:
        """Read the effective allocation percentage."""
        mode = self.entry.data[CONF_PERCENTAGE_MODE]
        if mode == PERCENTAGE_MODE_FIXED:
            return float(
                self.get_option(CONF_FIXED_PERCENTAGE, DEFAULT_FIXED_PERCENTAGE)
            )

        entity_id = self.entry.data.get(CONF_PERCENTAGE_ENTITY)
        if not entity_id:
            raise _PercentageInvalidError("percentage_entity_missing")

        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            raise _PercentageInvalidError("percentage_unavailable")

        try:
            return read_percentage(state)
        except HomeAssistantError as err:
            raise _PercentageInvalidError(str(err)) from err

    async def _async_read_synchronized_inputs(
        self, expected_end: datetime
    ) -> _SynchronizedInputs:
        """Read and validate synchronized utility meter inputs."""
        grid_entity = self.entry.data[CONF_GRID_IMPORT_ENTITY]
        shared_entity = self.entry.data[CONF_SHARED_ENERGY_ENTITY]

        grid_state = self.hass.states.get(grid_entity)
        shared_state = self.hass.states.get(shared_entity)

        if (
            grid_state is None
            or shared_state is None
            or grid_state.state in ("unknown", "unavailable")
            or shared_state.state in ("unknown", "unavailable")
        ):
            raise _InputsUnavailableError()

        grid_reset = parse_reset_timestamp(
            grid_state.attributes.get(ATTR_LAST_RESET)
        )
        shared_reset = parse_reset_timestamp(
            shared_state.attributes.get(ATTR_LAST_RESET)
        )
        if grid_reset is None or shared_reset is None:
            raise _InvalidInputError("missing_last_reset")

        if not resets_match(grid_reset, shared_reset, self.reset_tolerance):
            raise _InputsUnsynchronizedError("reset_timestamps_differ")

        interval_end = dt_util.as_local(grid_reset)
        if not reset_matches_interval_end(
            grid_reset, expected_end, self.reset_tolerance
        ):
            raise _InputsUnsynchronizedError("reset_not_matching_expected_interval")

        interval_id = interval_id_from_end(interval_end)

        try:
            imported_kwh = read_utility_meter_last_period_kwh(grid_state)
            shared_kwh = read_utility_meter_last_period_kwh(shared_state)
        except HomeAssistantError as err:
            raise _InvalidInputError(str(err)) from err

        return _SynchronizedInputs(
            interval_id=interval_id,
            interval_end=interval_end,
            imported_kwh=imported_kwh,
            shared_kwh=shared_kwh,
        )

    async def async_reset_totals(self) -> None:
        """Reset cumulative totals and counters."""
        self.data.cumulative_imported = 0.0
        self.data.cumulative_shared = 0.0
        self.data.cumulative_used = 0.0
        self.data.cumulative_unused = 0.0
        self.data.cumulative_billable = 0.0
        self.data.processed_intervals = 0
        self.data.skipped_intervals = 0
        self.data.last_skip = None
        await self.storage.async_save(self.data.to_dict())
        self._notify_update()

    def get_effective_percentage(self) -> float | None:
        """Return the current effective allocation percentage."""
        mode = self.entry.data[CONF_PERCENTAGE_MODE]
        if mode == PERCENTAGE_MODE_FIXED:
            return float(
                self.get_option(CONF_FIXED_PERCENTAGE, DEFAULT_FIXED_PERCENTAGE)
            )

        entity_id = self.entry.data.get(CONF_PERCENTAGE_ENTITY)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return read_percentage(state)
        except HomeAssistantError:
            return None

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        """Return a diagnostics-friendly snapshot."""
        grid_state = self.hass.states.get(self.entry.data[CONF_GRID_IMPORT_ENTITY])
        shared_state = self.hass.states.get(self.entry.data[CONF_SHARED_ENERGY_ENTITY])
        percentage_state = None
        if self.entry.data.get(CONF_PERCENTAGE_MODE) == PERCENTAGE_MODE_ENTITY:
            entity_id = self.entry.data.get(CONF_PERCENTAGE_ENTITY)
            if entity_id:
                percentage_state = self.hass.states.get(entity_id)

        return {
            "status": self.status,
            "retry_deadline": (
                self._retry_deadline.isoformat() if self._retry_deadline else None
            ),
            "retry_warning_logged": self._retry_warning_logged,
            "source_entities": {
                "grid_import": _state_snapshot(grid_state),
                "shared_energy": _state_snapshot(shared_state),
                "percentage": _state_snapshot(percentage_state),
            },
            "effective_percentage": self.get_effective_percentage(),
            "last_processed_interval_id": self.data.last_processed_interval_id,
            "processed_intervals": self.data.processed_intervals,
            "skipped_intervals": self.data.skipped_intervals,
            "last_skip": (
                self.data.last_skip.to_dict() if self.data.last_skip else None
            ),
            "last_interval": (
                self.data.last_interval.to_dict() if self.data.last_interval else None
            ),
            "cumulative": {
                "imported": self.data.cumulative_imported,
                "shared": self.data.cumulative_shared,
                "used": self.data.cumulative_used,
                "unused": self.data.cumulative_unused,
                "billable": self.data.cumulative_billable,
            },
        }


class _SynchronizedInputs:
    """Validated synchronized inputs for one interval."""

    def __init__(
        self,
        interval_id: str,
        interval_end: datetime,
        imported_kwh: float,
        shared_kwh: float,
    ) -> None:
        """Initialize synchronized inputs."""
        self.interval_id = interval_id
        self.interval_end = interval_end
        self.imported_kwh = imported_kwh
        self.shared_kwh = shared_kwh


class _InputsUnavailableError(Exception):
    """Raised when source entities are unavailable."""


class _InputsUnsynchronizedError(Exception):
    """Raised when source entities are not synchronized."""

    def __init__(self, reason: str) -> None:
        """Initialize with a reason."""
        super().__init__(reason)
        self.reason = reason


class _InvalidInputError(Exception):
    """Raised when source entity data is invalid."""

    def __init__(self, reason: str) -> None:
        """Initialize with a reason."""
        super().__init__(reason)
        self.reason = reason


class _PercentageInvalidError(Exception):
    """Raised when the allocation percentage is invalid."""

    def __init__(self, reason: str) -> None:
        """Initialize with a reason."""
        super().__init__(reason)
        self.reason = reason


def _state_snapshot(state: Any) -> dict[str, Any] | None:
    """Return a compact state snapshot for diagnostics."""
    if state is None:
        return None
    return {
        "state": state.state,
        "attributes": dict(state.attributes),
        "available": state.state not in ("unknown", "unavailable"),
    }
