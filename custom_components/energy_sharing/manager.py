"""Settlement manager for Energy Sharing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
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
from homeassistant.util import dt as dt_util

from .active_loads import ActiveLoadConfig, ActiveLoadController
from .const import (
    BASELINE_INITIALIZED,
    BASELINE_NOT_INITIALIZED,
    CONF_ACTIVE_LOAD_ENABLED,
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_PRIORITY,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
    CONF_ALLOCATION_TOLERANCE_KWH,
    CONF_ALLOCATION_TOLERANCE_PCT,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PROCESSING_DELAY,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_PROVIDER_TIMESTAMP_ATTR,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_RECEIVER_TIMESTAMP_ATTR,
    CONF_RECONCILIATION_FAILURE_MODE,
    CONF_RETRY_INTERVAL,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    CONF_SHARED_TIMESTAMP_ATTR,
    CONF_SOURCE_FRESHNESS_TOLERANCE,
    DEFAULT_ALLOCATION_TOLERANCE_KWH,
    DEFAULT_ALLOCATION_TOLERANCE_PCT,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RECONCILIATION_FAILURE_MODE,
    DEFAULT_RETRY_INTERVAL,
    DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
    DOMAIN,
    MANUFACTURER,
    MODE_EXPORT_AND_PERCENTAGE,
    MODEL,
    RECONCILIATION_MATCHED,
    RECONCILIATION_MISMATCH_SKIP,
    RECONCILIATION_MISMATCH_WARN,
    RECONCILIATION_MODE_SKIP_INTERVAL,
    RECONCILIATION_NOT_CONFIGURED,
    SERVICE_CONFIRM,
    SERVICE_PROCESS_NOW,
    SERVICE_REINITIALIZE_BASELINE,
    SERVICE_RESET_TOTALS,
    STATUS_INITIALIZING_BASELINE,
    STATUS_INTERVAL_SKIPPED,
    STATUS_INVALID_SOURCE_VALUE,
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_RECONCILIATION_WARNING,
    STATUS_SOURCE_COUNTER_RESET,
    STATUS_WAITING_FOR_BOUNDARY,
    STATUS_WAITING_FOR_SOURCES,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .helpers import (
    CumulativeSourceReading,
    SourceValidationError,
    count_missed_intervals,
    get_completed_interval,
    interval_id_from_boundaries,
    read_cumulative_source,
    source_is_fresh_enough,
)
from .models import (
    BoundarySnapshot,
    FailureRecord,
    IntervalResult,
    SourceResetRecord,
    StorageData,
    calculate_interval_delta,
    calculate_settlement,
    evaluate_reconciliation,
)
from .models import (
    resolve_operating_mode as _resolve_operating_mode,
)
from .storage import EnergySharingStore

if TYPE_CHECKING:
    from . import EnergySharingConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _CurrentReadings:
    """Current cumulative readings for one boundary attempt."""

    interval_id: str
    interval_start: datetime
    interval_end: datetime
    receiver: CumulativeSourceReading
    shared: CumulativeSourceReading
    provider: CumulativeSourceReading | None


class _SourceUnavailableError(Exception):
    """Raised when source entities are unavailable."""


class _InvalidSourceError(Exception):
    """Raised when source values are invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _CounterResetError(Exception):
    """Raised when a cumulative counter reset is detected."""

    def __init__(
        self,
        source_key: str,
        entity_id: str,
        previous: float,
        current: float,
    ):
        super().__init__(source_key)
        self.source_key = source_key
        self.entity_id = entity_id
        self.previous = previous
        self.current = current


class EnergySharingManager:
    """Manage internal interval settlement, persistence, and scheduling."""

    def __init__(self, hass: HomeAssistant, entry: EnergySharingConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.storage = EnergySharingStore(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry.entry_id}",
        )
        self.data = StorageData()
        self.status = STATUS_WAITING_FOR_BOUNDARY
        self._unsub_schedule: CALLBACK_TYPE | None = None
        self._retry_unsub: CALLBACK_TYPE | None = None
        self._processing_lock = asyncio.Lock()
        self._retry_deadline: datetime | None = None
        self._retry_warning_logged = False
        self._entity_update_callbacks: list[CALLBACK_TYPE] = []
        self._update_listeners: list[Callable[[], None]] = []
        self._active_load_controller: ActiveLoadController | None = None

    @property
    def device_name(self) -> str:
        return self.entry.title

    @property
    def baseline_status(self) -> str:
        return (
            BASELINE_INITIALIZED
            if self.data.baseline_initialized
            else BASELINE_NOT_INITIALIZED
        )

    def get_option(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, default)

    @property
    def interval_minutes(self) -> int:
        return int(self.get_option(CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES))

    @property
    def processing_delay(self) -> int:
        return int(self.get_option(CONF_PROCESSING_DELAY, DEFAULT_PROCESSING_DELAY))

    @property
    def max_wait(self) -> int:
        return int(self.get_option(CONF_MAX_WAIT, DEFAULT_MAX_WAIT))

    @property
    def retry_interval(self) -> int:
        return int(self.get_option(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL))

    @property
    def source_freshness_tolerance(self) -> int:
        return int(
            self.get_option(
                CONF_SOURCE_FRESHNESS_TOLERANCE, DEFAULT_SOURCE_FRESHNESS_TOLERANCE
            )
        )

    @property
    def provider_export_total_source(self) -> str | None:
        source = self.get_option(CONF_PROVIDER_EXPORT_TOTAL_SOURCE)
        return str(source) if source else None

    @property
    def fixed_allocation_percentage(self) -> float | None:
        value = self.get_option(CONF_FIXED_ALLOCATION_PERCENTAGE)
        if value is None:
            return None
        return float(value)

    @property
    def operating_mode(self) -> str:
        return _resolve_operating_mode(
            self.provider_export_total_source is not None,
            self.fixed_allocation_percentage is not None,
        )

    def add_update_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._update_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._update_listeners:
                self._update_listeners.remove(listener)

        return remove_listener

    @callback
    def _notify_update(self) -> None:
        for listener in list(self._update_listeners):
            listener()

    async def async_setup(self) -> None:
        stored = await self.storage.async_load()
        if stored is not None:
            try:
                self.data = StorageData.from_dict(stored)
            except Exception:  # pragma: no cover - defensive hotfix path
                _LOGGER.warning(
                    "Failed to load existing storage for %s; "
                    "resetting runtime storage state",
                    self.entry.title,
                    exc_info=True,
                )
                self.data = StorageData()
                await self.storage.async_save(self.data.to_dict())

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
        self._setup_active_load_controller()
        self._schedule_next_processing()
        self._refresh_status()
        self._notify_update()

    async def async_unload(self) -> None:
        self._cancel_retry()
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None
        for unsub in self._entity_update_callbacks:
            unsub()
        self._entity_update_callbacks.clear()
        if self._active_load_controller is not None:
            await self._active_load_controller.async_unload()
            self._active_load_controller = None

    def async_reconfigure(self) -> None:
        for unsub in self._entity_update_callbacks:
            unsub()
        self._entity_update_callbacks.clear()
        self._subscribe_source_entities()
        self._setup_active_load_controller()
        self._schedule_next_processing()
        self._refresh_status()
        self._notify_update()

    def _setup_active_load_controller(self) -> None:
        loads = self._active_load_configs_from_options()
        if self._active_load_controller is None:
            self._active_load_controller = ActiveLoadController(
                self.hass, self, loads, self.interval_minutes
            )
            if self._active_load_controller.has_loads:
                self.hass.async_create_task(self._active_load_controller.async_setup())
            return

        self._active_load_controller.update_configuration(loads, self.interval_minutes)

    def _active_load_configs_from_options(self) -> list[ActiveLoadConfig]:
        raw = self.get_option(CONF_ACTIVE_LOADS, [])
        configs: list[ActiveLoadConfig] = []
        if not isinstance(raw, list):
            return configs
        for item in raw:
            if not isinstance(item, dict):
                continue
            switch_entity_id = item.get(CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID)
            power_sensor_entity_id = item.get(CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID)
            if not switch_entity_id or not power_sensor_entity_id:
                continue
            configs.append(
                ActiveLoadConfig(
                    switch_entity_id=str(switch_entity_id),
                    power_sensor_entity_id=str(power_sensor_entity_id),
                    priority=int(item.get(CONF_ACTIVE_LOAD_PRIORITY, len(configs))),
                    enabled=bool(item.get(CONF_ACTIVE_LOAD_ENABLED, True)),
                )
            )
        return sorted(configs, key=lambda cfg: cfg.priority)

    def _refresh_status(self) -> None:
        if not self.data.baseline_initialized:
            self.status = STATUS_INITIALIZING_BASELINE
        elif self.data.last_interval is not None:
            self.status = STATUS_READY
        else:
            self.status = STATUS_WAITING_FOR_BOUNDARY

    def _register_services(self) -> None:
        if self.hass.services.has_service(DOMAIN, SERVICE_PROCESS_NOW):
            return

        async def process_now_service(call: Any) -> None:
            entry = await self._resolve_entry_from_service(call)
            if entry is None:
                raise HomeAssistantError("config_entry_not_found")
            result = await entry.runtime_data.manager.async_process_now()
            _LOGGER.info("process_now result for %s: %s", entry.title, result)

        async def reset_totals_service(call: Any) -> None:
            if not call.data.get(SERVICE_CONFIRM):
                raise HomeAssistantError("confirmation_required")
            entry = await self._resolve_entry_from_service(call)
            if entry is None:
                raise HomeAssistantError("config_entry_not_found")
            await entry.runtime_data.manager.async_reset_totals()
            _LOGGER.info("Cumulative totals reset for %s", entry.title)

        async def reinitialize_baseline_service(call: Any) -> None:
            entry = await self._resolve_entry_from_service(call)
            if entry is None:
                raise HomeAssistantError("config_entry_not_found")
            result = await entry.runtime_data.manager.async_reinitialize_baseline()
            _LOGGER.info("reinitialize_baseline result for %s: %s", entry.title, result)

        self.hass.services.async_register(
            DOMAIN, SERVICE_PROCESS_NOW, process_now_service
        )
        self.hass.services.async_register(
            DOMAIN, SERVICE_RESET_TOTALS, reset_totals_service
        )
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_REINITIALIZE_BASELINE,
            reinitialize_baseline_service,
        )

    async def _resolve_entry_from_service(
        self, call: Any
    ) -> EnergySharingConfigEntry | None:
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

    def _source_entity_ids(self) -> list[str]:
        entity_ids = [
            self.entry.data[CONF_RECEIVER_IMPORT_TOTAL_SOURCE],
            self.entry.data[CONF_SHARED_ENERGY_TOTAL_SOURCE],
        ]
        provider = self.provider_export_total_source
        if provider:
            entity_ids.append(provider)
        return entity_ids

    def _subscribe_source_entities(self) -> None:
        @callback
        def _source_changed(event: Any) -> None:
            if self._retry_deadline is not None:
                self.hass.async_create_task(self._async_retry_processing())

        for entity_id in self._source_entity_ids():
            self._entity_update_callbacks.append(
                async_track_state_change_event(
                    self.hass, entity_id, _source_changed
                )
            )

    def _schedule_next_processing(self) -> None:
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None

        next_run = self._calculate_next_run(dt_util.now())
        self._unsub_schedule = async_track_point_in_time(
            self.hass,
            self._async_scheduled_processing,
            next_run,
        )

    def _calculate_next_run(self, now: datetime) -> datetime:
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
        self.hass.async_create_task(self._async_process_latest("scheduled"))
        self._schedule_next_processing()

    def _cancel_retry(self) -> None:
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    async def _async_retry_processing(self) -> None:
        if self._retry_deadline is None:
            return
        if dt_util.utcnow() >= self._retry_deadline:
            return
        await self._async_process_latest("retry")

    async def async_process_now(self) -> str:
        return await self._async_process_latest("manual")

    async def async_reinitialize_baseline(self) -> str:
        async with self._processing_lock:
            try:
                readings = await self._async_read_current_readings(dt_util.now())
            except (_SourceUnavailableError, _InvalidSourceError) as err:
                reason = getattr(err, "reason", "source_unavailable")
                return f"failed:{reason}"

            await self._async_establish_baseline(readings, force=True)
            await self.storage.async_save(self.data.to_dict())
            self.status = STATUS_INITIALIZING_BASELINE
            self._notify_update()
            return "baseline_reinitialized"

    async def _async_process_latest(self, trigger: str) -> str:
        async with self._processing_lock:
            previous_status = self.status
            self.status = STATUS_PROCESSING
            self._notify_update()

            try:
                return await self._async_attempt_processing(trigger)
            finally:
                if self.status == STATUS_PROCESSING:
                    self.status = previous_status
                self._notify_update()

    async def _async_attempt_processing(self, trigger: str) -> str:
        now = dt_util.now()
        interval_start, interval_end = get_completed_interval(
            now, self.interval_minutes
        )
        interval_id = interval_id_from_boundaries(interval_start, interval_end)

        if self._retry_deadline is None:
            self._retry_deadline = now + timedelta(seconds=self.max_wait)
            self._retry_warning_logged = False

        try:
            readings = await self._async_read_current_readings(now)
        except _SourceUnavailableError:
            self.status = STATUS_WAITING_FOR_SOURCES
            return await self._async_handle_retry(
                trigger, interval_id, "source_unavailable"
            )
        except _InvalidSourceError as err:
            self._clear_retry_state()
            self.status = STATUS_INVALID_SOURCE_VALUE
            self.data.invalid_reading_count += 1
            await self._async_record_failure(err.reason, interval_id)
            return f"skipped:{err.reason}"

        if readings.interval_id != interval_id:
            self._clear_retry_state()
            return "stale_boundary"

        if not self._sources_are_fresh(readings):
            self.status = STATUS_WAITING_FOR_SOURCES
            return await self._async_handle_retry(
                trigger, interval_id, "sources_not_fresh"
            )

        if not self.data.baseline_initialized:
            await self._async_establish_baseline(readings)
            await self.storage.async_save(self.data.to_dict())
            self.status = STATUS_INITIALIZING_BASELINE
            self._clear_retry_state()
            _LOGGER.info(
                "Established baseline for %s at %s",
                self.entry.title,
                interval_id,
            )
            return "baseline_initialized"

        if (
            self.data.last_processed_interval_id is not None
            and interval_id == self.data.last_processed_interval_id
        ):
            self._clear_retry_state()
            self.status = STATUS_READY
            return "duplicate"

        if (
            self.data.last_processed_interval_id is not None
            and interval_id < self.data.last_processed_interval_id
        ):
            self._clear_retry_state()
            return "stale"

        assert self.data.previous_snapshot is not None
        previous = self.data.previous_snapshot

        try:
            deltas = self._calculate_deltas(previous, readings)
        except _CounterResetError as err:
            return await self._async_handle_counter_reset(readings, err, interval_id)

        mode = self.operating_mode
        fixed_pct = self.fixed_allocation_percentage
        settlement = calculate_settlement(
            operating_mode=mode,
            imported=deltas["receiver_import_interval_kwh"],
            shared=deltas["shared_energy_interval_kwh"],
            provider_export=deltas.get("provider_export_interval_kwh"),
            fixed_percentage=fixed_pct,
        )

        reconciliation_status = RECONCILIATION_NOT_CONFIGURED
        accumulate = True

        if mode == MODE_EXPORT_AND_PERCENTAGE:
            expected = settlement["expected_shared_kwh"]
            assert expected is not None
            tolerance_kwh = float(
                self.get_option(
                    CONF_ALLOCATION_TOLERANCE_KWH, DEFAULT_ALLOCATION_TOLERANCE_KWH
                )
            )
            tolerance_pct = float(
                self.get_option(
                    CONF_ALLOCATION_TOLERANCE_PCT, DEFAULT_ALLOCATION_TOLERANCE_PCT
                )
            )
            reconciliation = evaluate_reconciliation(
                expected,
                deltas["shared_energy_interval_kwh"],
                tolerance_kwh,
                tolerance_pct,
            )
            settlement["allocation_difference_kwh"] = reconciliation[
                "allocation_difference_kwh"
            ]
            settlement["allocation_difference_pct"] = reconciliation[
                "allocation_difference_pct"
            ]

            if reconciliation["reconciled"]:
                reconciliation_status = RECONCILIATION_MATCHED
            else:
                failure_mode = self.get_option(
                    CONF_RECONCILIATION_FAILURE_MODE,
                    DEFAULT_RECONCILIATION_FAILURE_MODE,
                )
                self.data.reconciliation_mismatch_count += 1
                if failure_mode == RECONCILIATION_MODE_SKIP_INTERVAL:
                    reconciliation_status = RECONCILIATION_MISMATCH_SKIP
                    accumulate = False
                    self.status = STATUS_INTERVAL_SKIPPED
                    await self._async_advance_snapshot(readings)
                    await self._async_record_failure(
                        f"reconciliation_skip:diff_kwh={reconciliation['allocation_difference_kwh']:.6f}",
                        interval_id,
                        increment_skip=True,
                    )
                    self._clear_retry_state()
                    return "skipped:reconciliation_mismatch"

                reconciliation_status = RECONCILIATION_MISMATCH_WARN
                self.status = STATUS_RECONCILIATION_WARNING
                _LOGGER.warning(
                    "Reconciliation mismatch for %s interval %s, processing with "
                    "actual shared counter (expected=%.6f, actual=%.6f)",
                    self.entry.title,
                    interval_id,
                    expected,
                    deltas["shared_energy_interval_kwh"],
                )

        missed = count_missed_intervals(
            self.data.last_processed_interval_id,
            interval_id,
            self.interval_minutes,
        )

        result = IntervalResult(
            interval_id=interval_id,
            interval_start=interval_start,
            interval_end=interval_end,
            operating_mode=mode,
            receiver_import_interval_kwh=deltas["receiver_import_interval_kwh"],
            shared_energy_interval_kwh=deltas["shared_energy_interval_kwh"],
            used_shared_kwh=float(settlement["used_shared_kwh"]),
            unused_shared_kwh=float(settlement["unused_shared_kwh"]),
            billable_energy_kwh=float(settlement["billable_energy_kwh"]),
            provider_export_interval_kwh=settlement["provider_export_interval_kwh"],
            provider_export_source_type=str(
                settlement["provider_export_source_type"]
            ),
            expected_shared_kwh=settlement["expected_shared_kwh"],
            fixed_allocation_percentage=fixed_pct,
            effective_allocation_pct=settlement["effective_allocation_pct"],
            required_share_pct=settlement["required_share_pct"],
            ideal_share_pct=settlement["ideal_share_pct"],
            allocation_utilization_pct=settlement["allocation_utilization_pct"],
            consumption_coverage_pct=settlement["consumption_coverage_pct"],
            allocation_difference_kwh=settlement["allocation_difference_kwh"],
            allocation_difference_pct=settlement["allocation_difference_pct"],
            reconciliation_status=reconciliation_status,
            settlement_accumulated=accumulate,
            processed_at=dt_util.utcnow(),
        )

        await self._async_advance_snapshot(readings)
        if self._active_load_controller is not None:
            self._active_load_controller.notify_processed_interval(result.unused_shared_kwh)

        if accumulate:
            self.data.cumulative_receiver_import += result.receiver_import_interval_kwh
            self.data.cumulative_shared_energy += result.shared_energy_interval_kwh
            if result.provider_export_interval_kwh is not None:
                self.data.cumulative_provider_export += (
                    result.provider_export_interval_kwh
                )
            if result.expected_shared_kwh is not None:
                self.data.cumulative_expected_shared += result.expected_shared_kwh
            self.data.cumulative_used += result.used_shared_kwh
            self.data.cumulative_unused += result.unused_shared_kwh
            self.data.cumulative_billable_energy += result.billable_energy_kwh
            self.data.processed_intervals += 1
            if missed > 0:
                self.data.skipped_intervals += missed
                await self._async_record_failure(
                    f"missed_intervals:{missed}",
                    interval_id,
                    increment_skip=True,
                    save=False,
                )

        self.data.last_processed_interval_id = interval_id
        self.data.last_interval = result
        await self.storage.async_save(self.data.to_dict())

        self._clear_retry_state()
        if accumulate and reconciliation_status != RECONCILIATION_MISMATCH_WARN:
            self.status = STATUS_READY

        _LOGGER.info(
            "Processed interval %s for %s via %s (accumulated=%s)",
            interval_id,
            self.entry.title,
            trigger,
            accumulate,
        )
        return "processed" if accumulate else "processed_without_accumulation"

    async def _async_read_current_readings(self, now: datetime) -> _CurrentReadings:
        interval_start, interval_end = get_completed_interval(
            now, self.interval_minutes
        )
        interval_id = interval_id_from_boundaries(interval_start, interval_end)

        receiver_state = self.hass.states.get(
            self.entry.data[CONF_RECEIVER_IMPORT_TOTAL_SOURCE]
        )
        shared_state = self.hass.states.get(
            self.entry.data[CONF_SHARED_ENERGY_TOTAL_SOURCE]
        )
        if receiver_state is None or shared_state is None:
            raise _SourceUnavailableError()

        try:
            receiver = read_cumulative_source(
                receiver_state,
                self.get_option(CONF_RECEIVER_TIMESTAMP_ATTR),
            )
            shared = read_cumulative_source(
                shared_state,
                self.get_option(CONF_SHARED_TIMESTAMP_ATTR),
            )
        except SourceValidationError as err:
            if err.code == "source_unavailable":
                raise _SourceUnavailableError() from err
            raise _InvalidSourceError(err.code) from err

        provider: CumulativeSourceReading | None = None
        provider_entity = self.provider_export_total_source
        if provider_entity:
            provider_state = self.hass.states.get(provider_entity)
            if provider_state is None:
                raise _SourceUnavailableError()
            try:
                provider = read_cumulative_source(
                    provider_state,
                    self.get_option(CONF_PROVIDER_TIMESTAMP_ATTR),
                )
            except SourceValidationError as err:
                if err.code == "source_unavailable":
                    raise _SourceUnavailableError() from err
                raise _InvalidSourceError(err.code) from err

        return _CurrentReadings(
            interval_id=interval_id,
            interval_start=interval_start,
            interval_end=interval_end,
            receiver=receiver,
            shared=shared,
            provider=provider,
        )

    def _sources_are_fresh(self, readings: _CurrentReadings) -> bool:
        """Validate optional measurement timestamps when configured."""
        checks: list[tuple[CumulativeSourceReading, str | None]] = [
            (readings.receiver, self.get_option(CONF_RECEIVER_TIMESTAMP_ATTR)),
            (readings.shared, self.get_option(CONF_SHARED_TIMESTAMP_ATTR)),
        ]
        if readings.provider:
            checks.append(
                (readings.provider, self.get_option(CONF_PROVIDER_TIMESTAMP_ATTR))
            )

        if not any(attr for _, attr in checks):
            return True

        tolerance = self.source_freshness_tolerance
        boundary_end = readings.interval_end
        for reading, attr in checks:
            if not attr:
                continue
            if not source_is_fresh_enough(reading, boundary_end, tolerance):
                return False
        return True

    async def _async_establish_baseline(
        self, readings: _CurrentReadings, *, force: bool = False
    ) -> None:
        snapshot = BoundarySnapshot(
            interval_id=readings.interval_id,
            timestamp=dt_util.utcnow(),
            receiver_import_total_kwh=readings.receiver.total_kwh,
            shared_energy_total_kwh=readings.shared.total_kwh,
            provider_export_total_kwh=(
                readings.provider.total_kwh if readings.provider else None
            ),
        )
        self.data.previous_snapshot = snapshot
        self.data.baseline_initialized = True
        self.data.baseline_initialization_count += 1
        if force:
            self.data.last_processed_interval_id = None

    async def _async_advance_snapshot(self, readings: _CurrentReadings) -> None:
        self.data.previous_snapshot = BoundarySnapshot(
            interval_id=readings.interval_id,
            timestamp=dt_util.utcnow(),
            receiver_import_total_kwh=readings.receiver.total_kwh,
            shared_energy_total_kwh=readings.shared.total_kwh,
            provider_export_total_kwh=(
                readings.provider.total_kwh if readings.provider else None
            ),
        )

    def _calculate_deltas(
        self, previous: BoundarySnapshot, readings: _CurrentReadings
    ) -> dict[str, float]:
        receiver_delta, receiver_reset = calculate_interval_delta(
            readings.receiver.total_kwh, previous.receiver_import_total_kwh
        )
        if receiver_reset:
            raise _CounterResetError(
                "receiver_import",
                readings.receiver.entity_id,
                previous.receiver_import_total_kwh,
                readings.receiver.total_kwh,
            )

        shared_delta, shared_reset = calculate_interval_delta(
            readings.shared.total_kwh, previous.shared_energy_total_kwh
        )
        if shared_reset:
            raise _CounterResetError(
                "shared_energy",
                readings.shared.entity_id,
                previous.shared_energy_total_kwh,
                readings.shared.total_kwh,
            )

        deltas: dict[str, float] = {
            "receiver_import_interval_kwh": receiver_delta or 0.0,
            "shared_energy_interval_kwh": shared_delta or 0.0,
        }

        if readings.provider is not None:
            if previous.provider_export_total_kwh is None:
                raise _InvalidSourceError("provider_snapshot_missing")
            provider_delta, provider_reset = calculate_interval_delta(
                readings.provider.total_kwh, previous.provider_export_total_kwh
            )
            if provider_reset:
                raise _CounterResetError(
                    "provider_export",
                    readings.provider.entity_id,
                    previous.provider_export_total_kwh,
                    readings.provider.total_kwh,
                )
            deltas["provider_export_interval_kwh"] = provider_delta or 0.0

        return deltas

    async def _async_handle_counter_reset(
        self,
        readings: _CurrentReadings,
        err: _CounterResetError,
        interval_id: str,
    ) -> str:
        self._clear_retry_state()
        self.data.source_reset_count += 1
        self.data.last_source_reset = SourceResetRecord(
            timestamp=dt_util.utcnow(),
            source_key=err.source_key,
            entity_id=err.entity_id,
            previous_total_kwh=err.previous,
            new_total_kwh=err.current,
            interval_id=interval_id,
        )
        await self._async_establish_baseline(readings, force=False)
        self.data.skipped_intervals += 1
        await self._async_record_failure(
            f"counter_reset:{err.source_key}",
            interval_id,
            increment_skip=False,
        )
        self.status = STATUS_SOURCE_COUNTER_RESET
        _LOGGER.warning(
            "Counter reset detected for %s on %s (%s): %.3f -> %.3f",
            self.entry.title,
            err.source_key,
            interval_id,
            err.previous,
            err.current,
        )
        return f"skipped:counter_reset:{err.source_key}"

    async def _async_handle_retry(
        self,
        trigger: str,
        interval_id: str,
        reason: str,
    ) -> str:
        now = dt_util.utcnow()
        if self._retry_deadline is not None and now < self._retry_deadline:
            if not self._retry_warning_logged:
                _LOGGER.warning(
                    "Sources not ready for %s (%s), retrying until %s",
                    self.entry.title,
                    reason,
                    self._retry_deadline,
                )
                self._retry_warning_logged = True
            self._schedule_retry()
            return f"retrying:{reason}"

        self._clear_retry_state()
        await self._async_record_failure(reason, interval_id, increment_skip=True)
        return f"skipped:{reason}"

    def _schedule_retry(self) -> None:
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
        self._cancel_retry()
        self._retry_deadline = None
        self._retry_warning_logged = False

    async def _async_record_failure(
        self,
        reason: str,
        interval_id: str | None,
        *,
        increment_skip: bool = True,
        save: bool = True,
    ) -> None:
        if increment_skip:
            self.data.skipped_intervals += 1
        self.data.last_failure = FailureRecord(
            timestamp=dt_util.utcnow(),
            reason=reason,
            interval_id=interval_id,
        )
        if save:
            await self.storage.async_save(self.data.to_dict())
        self._notify_update()

    async def async_reset_totals(self) -> None:
        self.data.cumulative_receiver_import = 0.0
        self.data.cumulative_shared_energy = 0.0
        self.data.cumulative_provider_export = 0.0
        self.data.cumulative_expected_shared = 0.0
        self.data.cumulative_used = 0.0
        self.data.cumulative_unused = 0.0
        self.data.cumulative_billable_energy = 0.0
        self.data.processed_intervals = 0
        self.data.skipped_intervals = 0
        self.data.reconciliation_mismatch_count = 0
        self.data.last_failure = None
        await self.storage.async_save(self.data.to_dict())
        self._notify_update()

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        def _snap(state: Any) -> dict[str, Any] | None:
            if state is None:
                return None
            return {
                "state": state.state,
                "attributes": dict(state.attributes),
                "last_updated": (
                    state.last_updated.isoformat() if state.last_updated else None
                ),
            }

        return {
            "status": self.status,
            "baseline_status": self.baseline_status,
            "operating_mode": self.operating_mode,
            "retry_deadline": (
                self._retry_deadline.isoformat() if self._retry_deadline else None
            ),
            "source_entities": {
                "receiver_import_total": _snap(
                    self.hass.states.get(
                        self.entry.data[CONF_RECEIVER_IMPORT_TOTAL_SOURCE]
                    )
                ),
                "shared_energy_total": _snap(
                    self.hass.states.get(
                        self.entry.data[CONF_SHARED_ENERGY_TOTAL_SOURCE]
                    )
                ),
                "provider_export_total": _snap(
                    self.hass.states.get(self.provider_export_total_source)
                    if self.provider_export_total_source
                    else None
                ),
            },
            "previous_snapshot": (
                self.data.previous_snapshot.to_dict()
                if self.data.previous_snapshot
                else None
            ),
            "last_processed_interval_id": self.data.last_processed_interval_id,
            "processed_intervals": self.data.processed_intervals,
            "skipped_intervals": self.data.skipped_intervals,
            "baseline_initialization_count": self.data.baseline_initialization_count,
            "source_reset_count": self.data.source_reset_count,
            "invalid_reading_count": self.data.invalid_reading_count,
            "reconciliation_mismatch_count": self.data.reconciliation_mismatch_count,
            "last_failure": (
                self.data.last_failure.to_dict() if self.data.last_failure else None
            ),
            "last_source_reset": (
                self.data.last_source_reset.to_dict()
                if self.data.last_source_reset
                else None
            ),
            "last_interval": (
                self.data.last_interval.to_dict() if self.data.last_interval else None
            ),
            "cumulative": {
                "receiver_import": self.data.cumulative_receiver_import,
                "shared_energy": self.data.cumulative_shared_energy,
                "provider_export": self.data.cumulative_provider_export,
                "expected_shared": self.data.cumulative_expected_shared,
                "used": self.data.cumulative_used,
                "unused": self.data.cumulative_unused,
                "billable_energy": self.data.cumulative_billable_energy,
            },
            "active_loads": (
                self._active_load_controller.get_snapshot()
                if self._active_load_controller is not None
                else None
            ),
        }
