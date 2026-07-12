"""Config flow for Energy Sharing."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import EnergySharingConfigEntry
from .const import (
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


def _default_options() -> dict[str, Any]:
    return {
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
        CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
        CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
        CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
        CONF_RECONCILIATION_FAILURE_MODE: DEFAULT_RECONCILIATION_FAILURE_MODE,
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
            vol.Optional(
                CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
                default=defaults.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE),
            ): vol.Any(None, "", _CUMULATIVE_ENERGY_SELECTOR),
        vol.Optional(
            CONF_FIXED_ALLOCATION_PERCENTAGE,
            default=defaults.get(CONF_FIXED_ALLOCATION_PERCENTAGE),
        ): vol.Any(None, "", vol.All(vol.Coerce(float), vol.Range(min=0, max=200))),
        }
    )


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    schema: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
        ): selector.TextSelector(),
        vol.Optional(
            CONF_PROVIDER_EXPORT_TOTAL_SOURCE,
            default=defaults.get(CONF_PROVIDER_EXPORT_TOTAL_SOURCE),
        ): vol.Any(None, "", _CUMULATIVE_ENERGY_SELECTOR),
        vol.Optional(
            CONF_FIXED_ALLOCATION_PERCENTAGE,
            default=defaults.get(CONF_FIXED_ALLOCATION_PERCENTAGE),
        ): vol.Any(
            None,
            "",
            vol.All(
                vol.Coerce(float),
                vol.Range(min=MIN_ALLOCATION_PERCENTAGE, max=MAX_ALLOCATION_PERCENTAGE),
            ),
        ),
        vol.Required(
            CONF_INTERVAL_MINUTES,
            default=defaults.get(CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_INTERVAL_MINUTES, max=MAX_INTERVAL_MINUTES),
        ),
        vol.Required(
            CONF_PROCESSING_DELAY,
            default=defaults.get(CONF_PROCESSING_DELAY, DEFAULT_PROCESSING_DELAY),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_PROCESSING_DELAY, max=MAX_PROCESSING_DELAY),
        ),
        vol.Required(
            CONF_MAX_WAIT,
            default=defaults.get(CONF_MAX_WAIT, DEFAULT_MAX_WAIT),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_MAX_WAIT, max=MAX_MAX_WAIT)),
        vol.Required(
            CONF_RETRY_INTERVAL,
            default=defaults.get(CONF_RETRY_INTERVAL, DEFAULT_RETRY_INTERVAL),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_RETRY_INTERVAL, max=MAX_RETRY_INTERVAL),
        ),
        vol.Required(
            CONF_SOURCE_FRESHNESS_TOLERANCE,
            default=defaults.get(
                CONF_SOURCE_FRESHNESS_TOLERANCE, DEFAULT_SOURCE_FRESHNESS_TOLERANCE
            ),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(
                min=MIN_SOURCE_FRESHNESS_TOLERANCE,
                max=MAX_SOURCE_FRESHNESS_TOLERANCE,
            ),
        ),
        vol.Optional(
            CONF_RECEIVER_TIMESTAMP_ATTR,
            default=defaults.get(CONF_RECEIVER_TIMESTAMP_ATTR),
        ): vol.Any(None, "", selector.TextSelector()),
        vol.Optional(
            CONF_SHARED_TIMESTAMP_ATTR,
            default=defaults.get(CONF_SHARED_TIMESTAMP_ATTR),
        ): vol.Any(None, "", selector.TextSelector()),
        vol.Optional(
            CONF_PROVIDER_TIMESTAMP_ATTR,
            default=defaults.get(CONF_PROVIDER_TIMESTAMP_ATTR),
        ): vol.Any(None, "", selector.TextSelector()),
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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        defaults = {
            CONF_NAME: self.config_entry.title,
            **self.config_entry.options,
        }

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

            if not errors:
                new_title = user_input.pop(CONF_NAME)
                options = {**self.config_entry.options, **user_input}
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=new_title,
                )
                return self.async_create_entry(title="", data=options)

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
