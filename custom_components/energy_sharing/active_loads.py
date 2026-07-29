"""Runtime control for active load switches driven by measured power."""
# ruff: noqa: E501, SIM103

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import UnitOfPower
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTIVE_LOAD_CONTROL_ENABLED,
    CONF_ACTIVE_LOAD_CONTROL_TICK_SECONDS,
    CONF_ACTIVE_LOAD_CORRECTION_GAIN,
    CONF_ACTIVE_LOAD_ENERGY_DEADBAND_WH,
    CONF_ACTIVE_LOAD_IDLE_DETECTION_SECONDS,
    CONF_ACTIVE_LOAD_MAX_CORRECTION_WH,
    CONF_ACTIVE_LOAD_MIN_ACTIVE_POWER_W,
    CONF_ACTIVE_LOAD_MIN_OFF_SECONDS,
    CONF_ACTIVE_LOAD_MIN_ON_SECONDS,
    CONF_ACTIVE_LOAD_PREDICTIVE_EARLY_STOP,
    CONF_ACTIVE_LOAD_PREDICTIVE_MARGIN_WH,
    CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS,
    DEFAULT_ACTIVE_LOAD_CONTROL_ENABLED,
    DEFAULT_ACTIVE_LOAD_CONTROL_TICK_SECONDS,
    DEFAULT_ACTIVE_LOAD_CORRECTION_GAIN,
    DEFAULT_ACTIVE_LOAD_ENERGY_DEADBAND_WH,
    DEFAULT_ACTIVE_LOAD_IDLE_DETECTION_SECONDS,
    DEFAULT_ACTIVE_LOAD_MAX_CORRECTION_WH,
    DEFAULT_ACTIVE_LOAD_MIN_ACTIVE_POWER_W,
    DEFAULT_ACTIVE_LOAD_MIN_OFF_SECONDS,
    DEFAULT_ACTIVE_LOAD_MIN_ON_SECONDS,
    DEFAULT_ACTIVE_LOAD_PREDICTIVE_EARLY_STOP,
    DEFAULT_ACTIVE_LOAD_PREDICTIVE_MARGIN_WH,
    DEFAULT_ACTIVE_LOAD_STARTUP_GRACE_SECONDS,
)
from .helpers import floor_to_interval_boundary, parse_finite_number

_LOGGER = logging.getLogger(__name__)


def parse_power_watts(raw_value: str, unit: str | None) -> float | None:
    """Parse sensor power and normalize to watts."""
    value = parse_finite_number(raw_value)
    if value is None or value < 0:
        return None
    if unit == UnitOfPower.KILO_WATT:
        return value * 1000.0
    if unit == UnitOfPower.WATT:
        return value
    if unit in ("kW", "W"):
        return value * 1000.0 if unit == "kW" else value
    return None


@dataclass(slots=True)
class ActiveLoadConfig:
    """Static active load configuration."""

    switch_entity_id: str
    power_sensor_entity_id: str
    priority: int
    enabled: bool = True


@dataclass(slots=True)
class ActiveLoadRuntime:
    """Per-load runtime state for one integration entry."""

    config: ActiveLoadConfig
    switch_is_on: bool = False
    switch_available: bool = False
    measured_power_w: float = 0.0
    estimated_power_w: float | None = None
    owns_switch: bool = False
    accepting_power: bool = False
    startup_probing: bool = False
    idle_latched_until_interval_id: str | None = None
    manually_excluded_until_interval_id: str | None = None
    last_start_ts: datetime | None = None
    last_stop_ts: datetime | None = None
    below_threshold_since: datetime | None = None
    interval_energy_wh: float = 0.0
    allocated_target_wh: float = 0.0
    scheduled_runtime_s: float = 0.0
    skip_reason: str | None = None
    pending_stop_after_min_on: bool = False
    last_integration_context_id: str | None = None


@dataclass(slots=True)
class ActiveLoadIntervalState:
    """Interval-level target and tracking state."""

    interval_id: str | None = None
    interval_end: datetime | None = None
    interval_target_wh: float = 0.0
    previous_target_wh: float = 0.0
    previous_actual_wh: float = 0.0
    previous_tracking_error_wh: float = 0.0
    correction_wh: float = 0.0
    measured_total_wh: float = 0.0


class ActiveLoadController:
    """Measured-power active load controller."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: Any,
        loads: list[ActiveLoadConfig],
        interval_minutes: int,
    ) -> None:
        self.hass = hass
        self._manager = manager
        self._loads = [
            ActiveLoadRuntime(config=load_cfg)
            for load_cfg in sorted(loads, key=lambda i: i.priority)
        ]
        self._interval_minutes = interval_minutes
        self._tick_unsub: CALLBACK_TYPE | None = None
        self._state_unsubs: list[CALLBACK_TYPE] = []
        self._interval = ActiveLoadIntervalState()
        self._last_monotonic: float | None = None
        self._calibration_lock = asyncio.Lock()
        self._calibration_in_progress = False
        self._calibration_last_result: dict[str, int] | None = None
        self._calibration_last_finished_at: datetime | None = None
        self._last_unused_shared_wh: float | None = None
        self._last_interval_base_target_wh: float | None = None
        self._cumulative_mopped_up_wh: float = 0.0
        self._cumulative_overshoot_wh: float = 0.0
        self._cumulative_undershoot_wh: float = 0.0
        self._restore_estimated_power()

    @property
    def has_loads(self) -> bool:
        return bool(self._loads)

    @property
    def calibration_in_progress(self) -> bool:
        return self._calibration_in_progress

    @property
    def control_enabled(self) -> bool:
        return bool(
            self._opt(
                CONF_ACTIVE_LOAD_CONTROL_ENABLED,
                DEFAULT_ACTIVE_LOAD_CONTROL_ENABLED,
            )
        )

    def _opt(self, key: str, default: Any) -> Any:
        return self._manager.get_option(key, default)

    def _restore_estimated_power(self) -> None:
        get_estimates = getattr(self._manager, "get_active_load_estimated_power_map", None)
        if not callable(get_estimates):
            return
        estimates = get_estimates()
        for load in self._loads:
            power = estimates.get(load.config.switch_entity_id)
            if power is not None and power > 0:
                load.estimated_power_w = power

    def _schedule_persist_estimate(self, load: ActiveLoadRuntime) -> None:
        if load.estimated_power_w is None:
            return
        persist = getattr(self._manager, "async_persist_active_load_estimated_power", None)
        if not callable(persist):
            return
        self.hass.async_create_task(
            persist(load.config.switch_entity_id, load.estimated_power_w)
        )

    async def async_setup(self) -> None:
        self._subscribe_entities()
        self._schedule_tick()

    async def async_unload(self) -> None:
        if self._tick_unsub is not None:
            self._tick_unsub()
            self._tick_unsub = None
        for unsub in self._state_unsubs:
            unsub()
        self._state_unsubs.clear()
        for load in self._loads:
            if load.owns_switch:
                await self._async_turn_off_load(load, reason="unload")

    def _notify_entity_update(self) -> None:
        notify = getattr(self._manager, "notify_entities_update", None)
        if callable(notify):
            notify()

    async def async_calibrate_loads(self) -> dict[str, int]:
        """Sequentially learn baseline load power from real measurements."""
        async with self._calibration_lock:
            self._calibration_in_progress = True
            self._notify_entity_update()
            _LOGGER.info("Active load calibration started")
            try:
                startup_grace = int(
                    self._opt(
                        CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS,
                        DEFAULT_ACTIVE_LOAD_STARTUP_GRACE_SECONDS,
                    )
                )
                min_on = int(
                    self._opt(
                        CONF_ACTIVE_LOAD_MIN_ON_SECONDS,
                        DEFAULT_ACTIVE_LOAD_MIN_ON_SECONDS,
                    )
                )
                learn_seconds = max(min_on, startup_grace + 1)
                switch_on_wait_seconds = max(60, startup_grace + 1)
                min_active_power = float(
                    self._opt(
                        CONF_ACTIVE_LOAD_MIN_ACTIVE_POWER_W,
                        DEFAULT_ACTIVE_LOAD_MIN_ACTIVE_POWER_W,
                    )
                )
                calibrated = 0
                considered = 0

                for load in self._loads:
                    self._refresh_single_load_state(load)
                    if not load.config.enabled or not load.switch_available:
                        _LOGGER.info(
                            "Active load calibration skipped for %s (enabled=%s available=%s)",
                            load.config.switch_entity_id,
                            load.config.enabled,
                            load.switch_available,
                        )
                        continue
                    considered += 1
                    started_by_calibration = False
                    try:
                        _LOGGER.info(
                            "Active load calibration learning %s for %ss",
                            load.config.switch_entity_id,
                            learn_seconds,
                        )
                        if not load.switch_is_on:
                            await self._async_turn_on_load(
                                load, reason="calibration", force=True
                            )
                            started_by_calibration = True
                            waited_for_on = 0
                            while waited_for_on < switch_on_wait_seconds:
                                self._refresh_single_load_state(load)
                                if load.switch_is_on:
                                    break
                                wait_step = min(2, switch_on_wait_seconds - waited_for_on)
                                await asyncio.sleep(wait_step)
                                waited_for_on += wait_step

                        if not load.switch_is_on:
                            _LOGGER.info(
                                "Active load calibration could not confirm ON state for %s after %ss",
                                load.config.switch_entity_id,
                                switch_on_wait_seconds,
                            )
                            continue

                        # For manually-on loads, allow immediate learning from stable draw.
                        if load.last_start_ts is None:
                            load.last_start_ts = dt_util.now() - timedelta(
                                seconds=startup_grace + 1
                            )

                        timeout_seconds = max(learn_seconds, startup_grace + 60)
                        elapsed = 0
                        poll_seconds = 5
                        previous_estimate = load.estimated_power_w
                        while elapsed < timeout_seconds:
                            wait_step = min(poll_seconds, timeout_seconds - elapsed)
                            await asyncio.sleep(wait_step)
                            elapsed += wait_step
                            self._refresh_single_load_state(load)
                            self._update_learning(load)
                            if load.estimated_power_w is not None:
                                break
                        _LOGGER.info(
                            "Active load calibration window for %s: %ss (threshold=%.1fW measured=%.1fW)",
                            load.config.switch_entity_id,
                            elapsed,
                            min_active_power,
                            load.measured_power_w,
                        )
                        if load.estimated_power_w is not None:
                            calibrated += 1
                            _LOGGER.info(
                                "Active load calibration learned %s: %.1fW (measured=%.1fW)",
                                load.config.switch_entity_id,
                                load.estimated_power_w,
                                load.measured_power_w,
                            )
                        else:
                            _LOGGER.info(
                                "Active load calibration did not learn %s "
                                "(measured=%.1fW threshold=%.1fW)",
                                load.config.switch_entity_id,
                                load.measured_power_w,
                                min_active_power,
                            )
                        if (
                            previous_estimate is not None
                            and load.estimated_power_w is not None
                            and previous_estimate != load.estimated_power_w
                        ):
                            self._notify_entity_update()
                    except Exception:  # pragma: no cover - defensive runtime guard
                        _LOGGER.warning(
                            "Active load calibration failed for %s",
                            load.config.switch_entity_id,
                            exc_info=True,
                        )
                    finally:
                        if started_by_calibration:
                            await self._async_turn_off_load(
                                load, reason="calibration_done", force=True
                            )
                            self._refresh_single_load_state(load)

                result = {
                    "calibrated_loads": calibrated,
                    "considered_loads": considered,
                }
                self._calibration_last_result = result
                self._calibration_last_finished_at = dt_util.now()
                _LOGGER.info(
                    "Active load calibration finished: %s",
                    result,
                )
                return result
            finally:
                self._calibration_in_progress = False
                self._notify_entity_update()

    def update_configuration(self, loads: list[ActiveLoadConfig], interval_minutes: int) -> None:
        previous = {
            load.config.switch_entity_id: load.estimated_power_w for load in self._loads
        }
        self._loads = [
            ActiveLoadRuntime(config=load_cfg)
            for load_cfg in sorted(loads, key=lambda i: i.priority)
        ]
        self._interval_minutes = interval_minutes
        for load in self._loads:
            switch_entity_id = load.config.switch_entity_id
            stored = self._manager.get_active_load_estimated_power_map().get(
                switch_entity_id
            )
            if stored is not None and stored > 0:
                load.estimated_power_w = stored
            elif previous.get(switch_entity_id) is not None:
                load.estimated_power_w = previous[switch_entity_id]
        for unsub in self._state_unsubs:
            unsub()
        self._state_unsubs.clear()
        self._subscribe_entities()

    def notify_processed_interval(self, unused_shared_kwh: float) -> None:
        now = dt_util.now()
        # Apply the newly processed interval's budget to the upcoming control window.
        interval_end = floor_to_interval_boundary(
            now, self._interval_minutes
        ) + timedelta(minutes=self._interval_minutes)
        interval_start = interval_end - timedelta(minutes=self._interval_minutes)
        interval_id = f"{dt_util.as_utc(interval_start).isoformat()}|{dt_util.as_utc(interval_end).isoformat()}"

        if self._interval.interval_id != interval_id:
            self._roll_interval(interval_id, interval_end)

        base_target_wh = max(unused_shared_kwh * 1000.0, 0.0)
        self._last_unused_shared_wh = base_target_wh
        self._last_interval_base_target_wh = base_target_wh
        error_wh = self._interval.previous_target_wh - self._interval.previous_actual_wh

        # Accumulate mopped-up energy: what the loads actually consumed this interval.
        self._cumulative_mopped_up_wh += self._interval.previous_actual_wh
        if error_wh < 0:
            # Loads consumed more than targeted (overshoot).
            self._cumulative_overshoot_wh += -error_wh
        elif error_wh > 0:
            # Budget was available but not fully consumed (undershoot).
            self._cumulative_undershoot_wh += error_wh
        gain = float(self._opt(CONF_ACTIVE_LOAD_CORRECTION_GAIN, DEFAULT_ACTIVE_LOAD_CORRECTION_GAIN))
        max_corr = float(self._opt(CONF_ACTIVE_LOAD_MAX_CORRECTION_WH, DEFAULT_ACTIVE_LOAD_MAX_CORRECTION_WH))
        correction_wh = max(-max_corr, min(max_corr, gain * error_wh))
        capacity_wh = self._estimate_interval_capacity_wh(interval_end)

        self._interval.previous_tracking_error_wh = error_wh
        self._interval.correction_wh = correction_wh
        self._interval.interval_target_wh = max(0.0, min(base_target_wh + correction_wh, capacity_wh))

        _LOGGER.info(
            "Active load interval %s: unused=%.3fWh corr=%.3fWh "
            "cap=%.3fWh target=%.3fWh available_loads=%d estimated_loads=%d",
            interval_id,
            base_target_wh,
            correction_wh,
            capacity_wh,
            self._interval.interval_target_wh,
            len([load for load in self._loads if self._is_load_available(load)]),
            len(
                [
                    load
                    for load in self._loads
                    if load.estimated_power_w is not None and load.config.enabled
                ]
            ),
        )

    def get_snapshot(self) -> dict[str, Any]:
        now = dt_util.now()
        seconds_remaining = 0
        if self._interval.interval_end is not None:
            seconds_remaining = max(0, int((self._interval.interval_end - now).total_seconds()))
        return {
            "target_wh": self._interval.interval_target_wh,
            "measured_wh": self._interval.measured_total_wh,
            "remaining_wh": max(0.0, self._interval.interval_target_wh - self._interval.measured_total_wh),
            "tracking_error_wh": self._interval.previous_tracking_error_wh,
            "applied_correction_wh": self._interval.correction_wh,
            "seconds_remaining": seconds_remaining,
            "available_load_count": len(
                [load for load in self._loads if self._is_load_available(load)]
            ),
            "configured_load_count": len(self._loads),
            "estimated_load_count": len(
                [
                    load
                    for load in self._loads
                    if load.estimated_power_w is not None and load.config.enabled
                ]
            ),
            "control_enabled": self.control_enabled,
            "calibration_in_progress": self._calibration_in_progress,
            "calibration_last_result": self._calibration_last_result,
            "calibration_last_finished_at": (
                self._calibration_last_finished_at.isoformat()
                if self._calibration_last_finished_at is not None
                else None
            ),
            "interval_id": self._interval.interval_id,
            "last_unused_shared_wh": self._last_unused_shared_wh,
            "last_interval_base_target_wh": self._last_interval_base_target_wh,
            "cumulative_mopped_up_wh": self._cumulative_mopped_up_wh,
            "cumulative_overshoot_wh": self._cumulative_overshoot_wh,
            "cumulative_undershoot_wh": self._cumulative_undershoot_wh,
            "loads": [
                {
                    "switch_entity_id": load.config.switch_entity_id,
                    "power_sensor_entity_id": load.config.power_sensor_entity_id,
                    "priority": load.config.priority,
                    "enabled": load.config.enabled,
                    "switch_is_on": load.switch_is_on,
                    "switch_available": load.switch_available,
                    "measured_power_w": load.measured_power_w,
                    "estimated_power_w": load.estimated_power_w,
                    "owns_switch": load.owns_switch,
                    "accepting_power": load.accepting_power,
                    "startup_probing": load.startup_probing,
                    "idle_latched": bool(
                        self._interval.interval_id
                        and load.idle_latched_until_interval_id == self._interval.interval_id
                    ),
                    "manually_excluded": bool(
                        self._interval.interval_id
                        and load.manually_excluded_until_interval_id
                        == self._interval.interval_id
                    ),
                    "interval_energy_wh": load.interval_energy_wh,
                    "allocated_target_wh": load.allocated_target_wh,
                    "scheduled_runtime_s": load.scheduled_runtime_s,
                    "skip_reason": load.skip_reason,
                    "last_start_ts": (
                        load.last_start_ts.isoformat() if load.last_start_ts else None
                    ),
                    "last_stop_ts": (
                        load.last_stop_ts.isoformat() if load.last_stop_ts else None
                    ),
                }
                for load in self._loads
            ],
        }

    def _subscribe_entities(self) -> None:
        @callback
        def _switch_listener(event: Any) -> None:
            self._handle_switch_change(event)

        @callback
        def _power_listener(event: Any) -> None:
            self._handle_power_change(event)

        for load in self._loads:
            self._state_unsubs.append(
                async_track_state_change_event(self.hass, load.config.switch_entity_id, _switch_listener)
            )
            self._state_unsubs.append(
                async_track_state_change_event(self.hass, load.config.power_sensor_entity_id, _power_listener)
            )
            self._refresh_single_load_state(load)

    def _schedule_tick(self) -> None:
        if self._tick_unsub is not None:
            self._tick_unsub()
        interval = int(self._opt(CONF_ACTIVE_LOAD_CONTROL_TICK_SECONDS, DEFAULT_ACTIVE_LOAD_CONTROL_TICK_SECONDS))

        @callback
        def _tick(_now: datetime) -> None:
            self.hass.async_create_task(self._async_tick())

        self._tick_unsub = async_call_later(self.hass, interval, _tick)

    async def _async_tick(self) -> None:
        try:
            self._integrate_energy()
            await self._apply_control()
        finally:
            self._schedule_tick()

    def _integrate_energy(self) -> None:
        now_mono = time.monotonic()
        if self._last_monotonic is None:
            self._last_monotonic = now_mono
            return
        elapsed = max(0.0, now_mono - self._last_monotonic)
        self._last_monotonic = now_mono

        total_wh = 0.0
        for load in self._loads:
            load.interval_energy_wh += load.measured_power_w * elapsed / 3600.0
            total_wh += load.interval_energy_wh
            self._update_learning(load)
        self._interval.measured_total_wh = total_wh

    def _update_learning(self, load: ActiveLoadRuntime) -> None:
        threshold = float(self._opt(CONF_ACTIVE_LOAD_MIN_ACTIVE_POWER_W, DEFAULT_ACTIVE_LOAD_MIN_ACTIVE_POWER_W))
        startup_grace = int(self._opt(CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS, DEFAULT_ACTIVE_LOAD_STARTUP_GRACE_SECONDS))
        now = dt_util.now()
        if not load.switch_is_on:
            return
        # Learn from any ON period (manual, other automation, or integration-owned).
        # Startup grace only applies when we know the recent start timestamp.
        if load.last_start_ts and (now - load.last_start_ts).total_seconds() < startup_grace:
            return
        if load.measured_power_w <= threshold:
            return
        alpha = 0.2
        previous_estimate = load.estimated_power_w
        load.estimated_power_w = (
            load.measured_power_w
            if load.estimated_power_w is None
            else (alpha * load.measured_power_w + (1 - alpha) * load.estimated_power_w)
        )
        if previous_estimate is None or abs(load.estimated_power_w - previous_estimate) >= 5.0:
            _LOGGER.info(
                "Active load learned power for %s: %.1fW (measured=%.1fW)",
                load.config.switch_entity_id,
                load.estimated_power_w,
                load.measured_power_w,
            )
        if (
            previous_estimate is None
            or abs(load.estimated_power_w - previous_estimate) >= 1.0
        ):
            self._schedule_persist_estimate(load)

    async def _apply_control(self) -> None:
        if self._interval.interval_end is None:
            return
        now = dt_util.now()
        if now >= self._interval.interval_end:
            await self._async_end_interval()
            return
        self._refresh_all_states()
        if self._calibration_in_progress:
            return

        if not self.control_enabled:
            return

        remaining_wh = max(0.0, self._interval.interval_target_wh - self._interval.measured_total_wh)
        deadband_wh = float(self._opt(CONF_ACTIVE_LOAD_ENERGY_DEADBAND_WH, DEFAULT_ACTIVE_LOAD_ENERGY_DEADBAND_WH))
        predictive_stop = bool(self._opt(CONF_ACTIVE_LOAD_PREDICTIVE_EARLY_STOP, DEFAULT_ACTIVE_LOAD_PREDICTIVE_EARLY_STOP))
        predictive_margin = float(self._opt(CONF_ACTIVE_LOAD_PREDICTIVE_MARGIN_WH, DEFAULT_ACTIVE_LOAD_PREDICTIVE_MARGIN_WH))

        if remaining_wh <= deadband_wh:
            for load in self._loads:
                await self._async_maybe_stop_owned(load, "target_reached")
            return

        if predictive_stop:
            tick = int(self._opt(CONF_ACTIVE_LOAD_CONTROL_TICK_SECONDS, DEFAULT_ACTIVE_LOAD_CONTROL_TICK_SECONDS))
            expected_next_wh = sum(
                max(load.measured_power_w, load.estimated_power_w or 0.0) * tick / 3600.0
                for load in self._loads
                if load.switch_is_on and load.owns_switch
            )
            if self._interval.measured_total_wh + expected_next_wh > self._interval.interval_target_wh + deadband_wh + predictive_margin:
                for load in reversed(self._loads):
                    if load.switch_is_on and load.owns_switch:
                        await self._async_maybe_stop_owned(load, "predictive_overshoot")
                        break

        self._allocate_targets(remaining_wh)
        for load in self._loads:
            if not self._is_load_available(load):
                await self._async_maybe_stop_owned(load, "not_available")
                if not load.switch_is_on:
                    load.skip_reason = "not_available"
                continue
            if load.allocated_target_wh > 0 and not load.switch_is_on:
                await self._async_turn_on_load(load, reason="scheduled")
            elif load.allocated_target_wh <= 0:
                await self._async_maybe_stop_owned(load, "no_allocation")
                if not load.switch_is_on:
                    load.skip_reason = "no_allocation"

    def _allocate_targets(self, remaining_wh: float) -> None:
        for load in self._loads:
            load.allocated_target_wh = 0.0
            load.scheduled_runtime_s = 0.0
        remaining_seconds = max(0.0, (self._interval.interval_end - dt_util.now()).total_seconds()) if self._interval.interval_end else 0.0
        for load in self._loads:
            if remaining_wh <= 0:
                break
            if not self._is_load_available(load):
                continue
            p = load.estimated_power_w or load.measured_power_w
            if p <= 0:
                continue
            capacity = p * remaining_seconds / 3600.0
            assigned = min(remaining_wh, capacity)
            load.allocated_target_wh = assigned
            load.scheduled_runtime_s = assigned * 3600.0 / p if p > 0 else 0.0
            remaining_wh -= assigned

    async def _async_turn_on_load(
        self, load: ActiveLoadRuntime, reason: str, *, force: bool = False
    ) -> None:
        if not self.control_enabled and not force:
            return
        min_off = int(self._opt(CONF_ACTIVE_LOAD_MIN_OFF_SECONDS, DEFAULT_ACTIVE_LOAD_MIN_OFF_SECONDS))
        now = dt_util.now()
        if load.last_stop_ts and (now - load.last_stop_ts).total_seconds() < min_off:
            return
        context = Context()
        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": load.config.switch_entity_id},
            blocking=True,
            context=context,
        )
        load.owns_switch = True
        load.startup_probing = True
        load.last_start_ts = now
        load.last_integration_context_id = context.id
        load.skip_reason = reason
        _LOGGER.info(
            "Active load %s turned on (reason=%s owns=%s)",
            load.config.switch_entity_id,
            reason,
            load.owns_switch,
        )

    async def _async_turn_off_load(
        self, load: ActiveLoadRuntime, reason: str, *, force: bool = False
    ) -> None:
        if not self.control_enabled and not force:
            return
        context = Context()
        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": load.config.switch_entity_id},
            blocking=True,
            context=context,
        )
        load.last_stop_ts = dt_util.now()
        load.last_integration_context_id = context.id
        load.owns_switch = False
        load.startup_probing = False
        load.skip_reason = reason
        load.pending_stop_after_min_on = False
        _LOGGER.info(
            "Active load %s turned off (reason=%s)",
            load.config.switch_entity_id,
            reason,
        )

    async def _async_maybe_stop_owned(self, load: ActiveLoadRuntime, reason: str) -> None:
        if not load.switch_is_on or not load.owns_switch:
            return
        min_on = int(self._opt(CONF_ACTIVE_LOAD_MIN_ON_SECONDS, DEFAULT_ACTIVE_LOAD_MIN_ON_SECONDS))
        now = dt_util.now()
        if load.last_start_ts and (now - load.last_start_ts).total_seconds() < min_on:
            load.pending_stop_after_min_on = True
            return
        await self._async_turn_off_load(load, reason)

    async def _async_end_interval(self) -> None:
        for load in self._loads:
            await self._async_maybe_stop_owned(load, "interval_end")

    def _roll_interval(self, interval_id: str, interval_end: datetime) -> None:
        self._interval.previous_actual_wh = self._interval.measured_total_wh
        self._interval.previous_target_wh = self._interval.interval_target_wh
        self._interval.interval_id = interval_id
        self._interval.interval_end = interval_end
        self._interval.measured_total_wh = 0.0
        self._interval.interval_target_wh = 0.0
        for load in self._loads:
            load.interval_energy_wh = 0.0
            load.allocated_target_wh = 0.0
            load.scheduled_runtime_s = 0.0
            load.idle_latched_until_interval_id = None
            load.manually_excluded_until_interval_id = None
            load.accepting_power = False
            load.startup_probing = False
            load.pending_stop_after_min_on = False

    def _estimate_interval_capacity_wh(self, interval_end: datetime) -> float:
        remaining_seconds = max(0.0, (interval_end - dt_util.now()).total_seconds())
        capacity = 0.0
        for load in self._loads:
            if not self._is_load_available(load):
                continue
            p = load.estimated_power_w or load.measured_power_w
            if p <= 0:
                continue
            capacity += p * remaining_seconds / 3600.0
        return capacity

    def _is_load_available(self, load: ActiveLoadRuntime) -> bool:
        if not load.config.enabled:
            return False
        if not load.switch_available:
            return False
        if self._interval.interval_id and load.manually_excluded_until_interval_id == self._interval.interval_id:
            return False
        if self._interval.interval_id and load.idle_latched_until_interval_id == self._interval.interval_id:
            return False
        return True

    def _refresh_all_states(self) -> None:
        for load in self._loads:
            self._refresh_single_load_state(load)
            self._update_accepting_power(load)

    def _refresh_single_load_state(self, load: ActiveLoadRuntime) -> None:
        switch_state = self.hass.states.get(load.config.switch_entity_id)
        load.switch_available = switch_state is not None and switch_state.state not in ("unavailable", "unknown")
        load.switch_is_on = bool(switch_state and switch_state.state == "on")
        power_state = self.hass.states.get(load.config.power_sensor_entity_id)
        if power_state is None:
            load.measured_power_w = 0.0
            return
        power = parse_power_watts(power_state.state, power_state.attributes.get("unit_of_measurement"))
        load.measured_power_w = power if power is not None else 0.0

    def _update_accepting_power(self, load: ActiveLoadRuntime) -> None:
        threshold = float(self._opt(CONF_ACTIVE_LOAD_MIN_ACTIVE_POWER_W, DEFAULT_ACTIVE_LOAD_MIN_ACTIVE_POWER_W))
        idle_seconds = int(self._opt(CONF_ACTIVE_LOAD_IDLE_DETECTION_SECONDS, DEFAULT_ACTIVE_LOAD_IDLE_DETECTION_SECONDS))
        startup_grace = int(self._opt(CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS, DEFAULT_ACTIVE_LOAD_STARTUP_GRACE_SECONDS))
        now = dt_util.now()

        if not load.switch_is_on:
            load.accepting_power = False
            load.below_threshold_since = None
            return

        if load.last_start_ts and (now - load.last_start_ts).total_seconds() < startup_grace:
            load.startup_probing = True
            load.accepting_power = False
            return
        load.startup_probing = False

        if load.measured_power_w > threshold:
            load.accepting_power = True
            load.below_threshold_since = None
            return

        if load.below_threshold_since is None:
            load.below_threshold_since = now
            return
        if (now - load.below_threshold_since).total_seconds() >= idle_seconds:
            load.accepting_power = False
            if self._interval.interval_id:
                load.idle_latched_until_interval_id = self._interval.interval_id

    @callback
    def _handle_switch_change(self, event: Any) -> None:
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        matched = next(
            (
                load
                for load in self._loads
                if load.config.switch_entity_id == entity_id
            ),
            None,
        )
        if matched is None:
            return
        now = dt_util.now()
        was_on = bool(old_state and old_state.state == "on")
        is_on = new_state.state == "on"
        context_id = getattr(new_state.context, "id", None)
        if context_id is not None and context_id == matched.last_integration_context_id:
            return
        if is_on and not was_on:
            matched.last_start_ts = now
            matched.below_threshold_since = None
        elif was_on and not is_on:
            matched.last_stop_ts = now
            matched.startup_probing = False
        # User/manual action: release ownership and exclude for current interval.
        matched.owns_switch = False
        if self._interval.interval_id is not None:
            matched.manually_excluded_until_interval_id = self._interval.interval_id

    @callback
    def _handle_power_change(self, event: Any) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        matched = next(
            (
                load
                for load in self._loads
                if load.config.power_sensor_entity_id == entity_id
            ),
            None,
        )
        if matched is None:
            return
        parsed = parse_power_watts(new_state.state, new_state.attributes.get("unit_of_measurement"))
        matched.measured_power_w = parsed if parsed is not None and math.isfinite(parsed) and parsed >= 0 else 0.0
