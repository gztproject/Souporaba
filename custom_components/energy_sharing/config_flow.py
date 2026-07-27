"""Config flow for Energy Sharing."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from . import EnergySharingConfigEntry
from .const import (
    CONF_ACTIVE_LOAD_CONTROL_ENABLED,
    CONF_ACTIVE_LOAD_ENABLED,
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_PRIORITY,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
    CONF_ACTIVE_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_SWITCH_ENTITY_ID,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_FIXED_PERCENTAGE,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PROCESSING_DELAY,
    CONF_PROVIDER_EXPORT_SOURCE,
    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
    CONF_PROVIDER_TIMESTAMP_ATTR,
    CONF_RECEIVER_IMPORT_SOURCE,
    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
    CONF_RECEIVER_TIMESTAMP_ATTR,
    CONF_RECONCILIATION_FAILURE_MODE,
    CONF_RETRY_INTERVAL,
    CONF_SHARED_ENERGY_TOTAL_SOURCE,
    CONF_SHARED_TIMESTAMP_ATTR,
    CONF_SOURCE_FRESHNESS_TOLERANCE,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_ACTIVE_LOAD_CONTROL_ENABLED,
    DEFAULT_ACTIVE_LOADS,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_NAME,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RECONCILIATION_FAILURE_MODE,
    DEFAULT_RETRY_INTERVAL,
    DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
    DOMAIN,
    MAX_ALLOCATION_PERCENTAGE,
    MAX_INTERVAL_MINUTES,
    MAX_MAX_WAIT,
    MAX_PROCESSING_DELAY,
    MAX_RETRY_INTERVAL,
    MAX_SOURCE_FRESHNESS_TOLERANCE,
    MIN_ALLOCATION_PERCENTAGE,
    MIN_INTERVAL_MINUTES,
    MIN_MAX_WAIT,
    MIN_PROCESSING_DELAY,
    MIN_RETRY_INTERVAL,
    MIN_SOURCE_FRESHNESS_TOLERANCE,
    RECONCILIATION_MODE_SKIP_INTERVAL,
    RECONCILIATION_MODE_WARN,
)
from .helpers import SourceValidationError, validate_cumulative_source

_LOGGER = logging.getLogger(__name__)

_CUMULATIVE_ENERGY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain=["sensor"],
        device_class=["energy"],
    )
)

_PERCENTAGE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_ALLOCATION_PERCENTAGE,
        max=MAX_ALLOCATION_PERCENTAGE,
        step=0.01,
        mode=selector.NumberSelectorMode.BOX,
    )
)

_USER_PERCENTAGE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=MAX_ALLOCATION_PERCENTAGE,
        step=0.01,
        mode=selector.NumberSelectorMode.BOX,
    )
)

_TEXT_SELECTOR = selector.TextSelector()
_SWITCH_MULTI_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch"], multiple=True)
)
_POWER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["sensor"], device_class=["power"])
)


def _integer_selector(*, minimum: int, maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _optional_field(key: str, defaults: dict[str, Any] | None) -> vol.Optional:
    """Build an optional marker without injecting None as a default value."""
    if defaults and defaults.get(key) not in (None, ""):
        return vol.Optional(key, default=defaults[key])
    return vol.Optional(key)


def _default_options() -> dict[str, Any]:
    return {
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
        CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
        CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
        CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
        CONF_RECONCILIATION_FAILURE_MODE: DEFAULT_RECONCILIATION_FAILURE_MODE,
        CONF_ACTIVE_LOADS: DEFAULT_ACTIVE_LOADS,
        CONF_ACTIVE_LOAD_CONTROL_ENABLED: DEFAULT_ACTIVE_LOAD_CONTROL_ENABLED,
    }


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
            ): selector.TextSelector(),
            vol.Required(
                CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
                default=defaults.get(CONF_RECEIVER_IMPORT_TOTAL_SOURCE),
            ): _CUMULATIVE_ENERGY_SELECTOR,
            vol.Required(
                CONF_SHARED_ENERGY_TOTAL_SOURCE,
                default=defaults.get(CONF_SHARED_ENERGY_TOTAL_SOURCE),
            ): _CUMULATIVE_ENERGY_SELECTOR,
            _optional_field(
                CONF_PROVIDER_EXPORT_TOTAL_SOURCE, defaults
            ): _CUMULATIVE_ENERGY_SELECTOR,
            _optional_field(
                CONF_FIXED_ALLOCATION_PERCENTAGE, defaults
            ): _USER_PERCENTAGE_SELECTOR,
        }
    )


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    active_load_switches = [
        item.get(CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID)
        for item in defaults.get(CONF_ACTIVE_LOADS, [])
        if isinstance(item, dict)
        and item.get(CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID)
        and item.get(CONF_ACTIVE_LOAD_ENABLED, True)
    ]
    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
        ): selector.TextSelector(),
        _optional_field(CONF_PROVIDER_EXPORT_TOTAL_SOURCE, defaults): (
            _CUMULATIVE_ENERGY_SELECTOR
        ),
        _optional_field(CONF_FIXED_ALLOCATION_PERCENTAGE, defaults): (
            _PERCENTAGE_SELECTOR
        ),
        vol.Required(
            CONF_INTERVAL_MINUTES,
            default=defaults.get(CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES),
        ): _integer_selector(
            minimum=MIN_INTERVAL_MINUTES,
            maximum=MAX_INTERVAL_MINUTES,
        ),
        vol.Required(
            CONF_PROCESSING_DELAY,
            default=defaults.get(CONF_PROCESSING_DELAY, DEFAULT_PROCESSING_DELAY),
        ): _integer_selector(
            minimum=MIN_PROCESSING_DELAY,
            maximum=MAX_PROCESSING_DELAY,
        ),
        vol.Required(
            CONF_MAX_WAIT,
            default=defaults.get(CONF_MAX_WAIT, DEFAULT_MAX_WAIT),
        ): _integer_selector(minimum=MIN_MAX_WAIT, maximum=MAX_MAX_WAIT),
        vol.Required(
            CONF_RETRY_INTERVAL,
            default=defaults.get(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL),
        ): _integer_selector(
            minimum=MIN_RETRY_INTERVAL,
            maximum=MAX_RETRY_INTERVAL,
        ),
        vol.Required(
            CONF_SOURCE_FRESHNESS_TOLERANCE,
            default=defaults.get(
                CONF_SOURCE_FRESHNESS_TOLERANCE, DEFAULT_SOURCE_FRESHNESS_TOLERANCE
            ),
        ): _integer_selector(
            minimum=MIN_SOURCE_FRESHNESS_TOLERANCE,
            maximum=MAX_SOURCE_FRESHNESS_TOLERANCE,
        ),
        _optional_field(CONF_RECEIVER_TIMESTAMP_ATTR, defaults): _TEXT_SELECTOR,
        _optional_field(CONF_SHARED_TIMESTAMP_ATTR, defaults): _TEXT_SELECTOR,
        _optional_field(CONF_PROVIDER_TIMESTAMP_ATTR, defaults): _TEXT_SELECTOR,
        vol.Optional("active_load_switches", default=active_load_switches): (
            _SWITCH_MULTI_SELECTOR
        ),
        vol.Required(
            CONF_ACTIVE_LOAD_CONTROL_ENABLED,
            default=defaults.get(
                CONF_ACTIVE_LOAD_CONTROL_ENABLED,
                DEFAULT_ACTIVE_LOAD_CONTROL_ENABLED,
            ),
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_RECONCILIATION_FAILURE_MODE,
            default=defaults.get(
                CONF_RECONCILIATION_FAILURE_MODE,
                DEFAULT_RECONCILIATION_FAILURE_MODE,
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=RECONCILIATION_MODE_WARN,
                        label="reconciliation_mode_warn",
                    ),
                    selector.SelectOptionDict(
                        value=RECONCILIATION_MODE_SKIP_INTERVAL,
                        label="reconciliation_mode_skip_interval",
                    ),
                ],
                translation_key="reconciliation_failure_mode",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
    return vol.Schema(schema)


def _clean_optional(value: Any) -> Any:
    if value in (None, ""):
        return None
    return value


def _validate_percentage_or_export(
    user_input: dict[str, Any],
) -> dict[str, str]:
    errors: dict[str, str] = {}
    provider = user_input.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE)
    percentage = user_input.get(CONF_FIXED_ALLOCATION_PERCENTAGE)

    if not provider and percentage is None:
        errors["base"] = "percentage_or_export_required"
        return errors

    if percentage is not None and (
        percentage <= 0 or percentage > MAX_ALLOCATION_PERCENTAGE
    ):
        errors[CONF_FIXED_ALLOCATION_PERCENTAGE] = "percentage_invalid"

    return errors


class EnergySharingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Sharing."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    @staticmethod
    async def async_migrate_entry(
        hass: HomeAssistant, config_entry: EnergySharingConfigEntry
    ) -> bool:
        if config_entry.version >= CONFIG_ENTRY_VERSION:
            return True

        data = dict(config_entry.data)
        options = dict(config_entry.options)

        if config_entry.version <= 2:
            data = {
                CONF_RECEIVER_IMPORT_TOTAL_SOURCE: data.get(
                    CONF_RECEIVER_IMPORT_TOTAL_SOURCE,
                    data.get(CONF_RECEIVER_IMPORT_SOURCE, ""),
                ),
                CONF_SHARED_ENERGY_TOTAL_SOURCE: data.get(
                    CONF_SHARED_ENERGY_TOTAL_SOURCE,
                    "",
                ),
            }

        # Legacy single active-load keys to list migration.
        if CONF_ACTIVE_LOADS not in options:
            legacy_switch = options.pop(CONF_ACTIVE_SWITCH_ENTITY_ID, None)
            legacy_power = options.pop(CONF_ACTIVE_POWER_SENSOR_ENTITY_ID, None)
            if legacy_switch and legacy_power:
                options[CONF_ACTIVE_LOADS] = [
                    {
                        CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: legacy_switch,
                        CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: legacy_power,
                        CONF_ACTIVE_LOAD_PRIORITY: 0,
                        CONF_ACTIVE_LOAD_ENABLED: True,
                    }
                ]
            options = {
                **_default_options(),
                **options,
                CONF_PROVIDER_EXPORT_TOTAL_SOURCE: options.pop(
                    CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
                    data.pop(CONF_PROVIDER_EXPORT_SOURCE, None),
                ),
                CONF_FIXED_ALLOCATION_PERCENTAGE: options.pop(
                    CONF_FIXED_ALLOCATION_PERCENTAGE,
                    options.pop(CONF_FIXED_PERCENTAGE, None),
                ),
            }

        hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            options=options,
            version=CONFIG_ENTRY_VERSION,
        )
        return True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = dict(user_input)
            user_input[CONF_PROVIDER_EXPORT_TOTAL_SOURCE] = _clean_optional(
                user_input.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE)
            )
            pct = _clean_optional(user_input.get(CONF_FIXED_ALLOCATION_PERCENTAGE))
            user_input[CONF_FIXED_ALLOCATION_PERCENTAGE] = pct

            errors = _validate_percentage_or_export(user_input)
            if not errors:
                errors = await self._async_validate_sources(user_input)

            if not errors:
                receiver = user_input[CONF_RECEIVER_IMPORT_TOTAL_SOURCE]
                shared = user_input[CONF_SHARED_ENERGY_TOTAL_SOURCE]
                await self.async_set_unique_id(f"{receiver}|{shared}")
                self._abort_if_unique_id_configured()

                options = _default_options()
                if user_input.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE):
                    options[CONF_PROVIDER_EXPORT_TOTAL_SOURCE] = user_input[
                        CONF_PROVIDER_EXPORT_TOTAL_SOURCE
                    ]
                if pct is not None:
                    options[CONF_FIXED_ALLOCATION_PERCENTAGE] = pct

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_RECEIVER_IMPORT_TOTAL_SOURCE: receiver,
                        CONF_SHARED_ENERGY_TOTAL_SOURCE: shared,
                    },
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def _async_validate_sources(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        entities = {
            "receiver_import": user_input[CONF_RECEIVER_IMPORT_TOTAL_SOURCE],
            "shared_energy": user_input[CONF_SHARED_ENERGY_TOTAL_SOURCE],
        }
        provider = user_input.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE)
        if provider:
            entities["provider_export"] = provider

        if len(set(entities.values())) != len(entities.values()):
            errors["base"] = "duplicate_sources"
            return errors

        for field, entity_id in entities.items():
            try:
                await validate_cumulative_source(self.hass, entity_id)
            except SourceValidationError as err:
                errors[field] = err.code

        return errors

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: EnergySharingConfigEntry,
    ) -> EnergySharingOptionsFlowHandler:
        return EnergySharingOptionsFlowHandler()


class EnergySharingOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Energy Sharing."""

    _pending_switches: list[str]
    _resolved_active_loads: list[dict[str, Any]]
    _pending_input: dict[str, Any]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        defaults = {
            CONF_NAME: self.config_entry.title,
            **self.config_entry.options,
        }
        self._resolved_active_loads = [
            dict(item)
            for item in self.config_entry.options.get(CONF_ACTIVE_LOADS, [])
            if isinstance(item, dict)
        ]

        if user_input is not None:
            user_input = dict(user_input)
            user_input[CONF_PROVIDER_EXPORT_TOTAL_SOURCE] = _clean_optional(
                user_input.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE)
            )
            pct = _clean_optional(user_input.get(CONF_FIXED_ALLOCATION_PERCENTAGE))
            user_input[CONF_FIXED_ALLOCATION_PERCENTAGE] = pct

            errors = _validate_percentage_or_export(user_input)
            provider = user_input.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE)
            if provider and provider in {
                self.config_entry.data[CONF_RECEIVER_IMPORT_TOTAL_SOURCE],
                self.config_entry.data[CONF_SHARED_ENERGY_TOTAL_SOURCE],
            }:
                errors["provider_export"] = "duplicate_sources"

            selected_switches = list(user_input.get("active_load_switches") or [])
            self._pending_input = user_input
            resolved, unresolved = self._resolve_active_load_sensors(selected_switches)
            self._resolved_active_loads = resolved
            self._pending_switches = unresolved

            if not errors and unresolved:
                return await self.async_step_active_load_sensors()

            if not errors:
                return await self._async_finish_options(user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults),
            errors=errors,
            description_placeholders={
                "receiver_import_total_source": self.config_entry.data[
                    CONF_RECEIVER_IMPORT_TOTAL_SOURCE
                ],
                "shared_energy_total_source": self.config_entry.data[
                    CONF_SHARED_ENERGY_TOTAL_SOURCE
                ],
            },
        )

    async def async_step_active_load_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for switch_entity_id in self._pending_switches:
                sensor = user_input.get(switch_entity_id)
                if not sensor:
                    errors[switch_entity_id] = "source_missing"
                    continue
                if self.hass.states.get(sensor) is None:
                    errors[switch_entity_id] = "source_missing"
                    continue
                self._resolved_active_loads.append(
                    {
                        CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: switch_entity_id,
                        CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: sensor,
                        CONF_ACTIVE_LOAD_PRIORITY: len(self._resolved_active_loads),
                        CONF_ACTIVE_LOAD_ENABLED: True,
                    }
                )
            if not errors:
                return await self._async_finish_options(self._pending_input)

        schema: dict[vol.Marker, Any] = {}
        for switch_entity_id in self._pending_switches:
            schema[vol.Required(switch_entity_id)] = _POWER_SELECTOR
        return self.async_show_form(
            step_id="active_load_sensors",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def _async_finish_options(self, user_input: dict[str, Any]) -> FlowResult:
        new_title = user_input.pop(CONF_NAME)
        user_input.pop("active_load_switches", None)
        user_input[CONF_ACTIVE_LOADS] = sorted(
            self._resolved_active_loads,
            key=lambda item: int(item.get(CONF_ACTIVE_LOAD_PRIORITY, 0)),
        )
        for timestamp_key in (
            CONF_RECEIVER_TIMESTAMP_ATTR,
            CONF_SHARED_TIMESTAMP_ATTR,
            CONF_PROVIDER_TIMESTAMP_ATTR,
        ):
            user_input[timestamp_key] = _clean_optional(
                user_input.get(timestamp_key)
            )
        options = {**self.config_entry.options, **user_input}
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            title=new_title,
        )
        return self.async_create_entry(title="", data=options)

    def _resolve_active_load_sensors(
        self, selected_switches: list[str]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []
        existing_by_switch = {
            item.get(CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID): item
            for item in self.config_entry.options.get(CONF_ACTIVE_LOADS, [])
            if isinstance(item, dict) and item.get(CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID)
        }

        ent_reg = er.async_get(self.hass)
        for index, switch_entity_id in enumerate(selected_switches):
            existing = existing_by_switch.get(switch_entity_id)
            if existing and self.hass.states.get(
                existing.get(CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID)
            ):
                resolved.append(
                    {
                        CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: switch_entity_id,
                        CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: existing.get(
                            CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID
                        ),
                        CONF_ACTIVE_LOAD_PRIORITY: index,
                        CONF_ACTIVE_LOAD_ENABLED: bool(
                            existing.get(CONF_ACTIVE_LOAD_ENABLED, True)
                        ),
                    }
                )
                continue

            switch_entry = ent_reg.async_get(switch_entity_id)
            device_id = switch_entry.device_id if switch_entry else None
            if device_id is None:
                unresolved.append(switch_entity_id)
                continue

            candidates: list[str] = []
            for candidate in er.async_entries_for_device(ent_reg, device_id):
                if candidate.domain != "sensor":
                    continue
                state = self.hass.states.get(candidate.entity_id)
                if state is None:
                    continue
                if state.attributes.get("device_class") != "power":
                    continue
                unit = state.attributes.get("unit_of_measurement")
                if unit not in ("W", "kW"):
                    continue
                try:
                    float(state.state)
                except (TypeError, ValueError):
                    continue
                candidates.append(candidate.entity_id)
            if len(candidates) == 1:
                resolved.append(
                    {
                        CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: switch_entity_id,
                        CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: candidates[0],
                        CONF_ACTIVE_LOAD_PRIORITY: index,
                        CONF_ACTIVE_LOAD_ENABLED: True,
                    }
                )
            else:
                unresolved.append(switch_entity_id)
        return resolved, unresolved
