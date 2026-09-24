"""Config flow for TaskPad."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEFAULT_INTERVAL,
    CONF_IMPORT_ENTITY,
    CONF_LOG_PATH,
    CONF_TOPIC_PREFIX,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_LOG_FILENAME,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
)

INTERVAL_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=1, max=3650))


class TaskPadConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup dialog."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        if user_input is not None:
            return self.async_create_entry(title="TaskPad", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_TOPIC_PREFIX, default=DEFAULT_TOPIC_PREFIX): str,
                vol.Required(CONF_LOG_PATH, default=DEFAULT_LOG_FILENAME): str,
                vol.Required(
                    CONF_DEFAULT_INTERVAL, default=DEFAULT_INTERVAL_DAYS
                ): INTERVAL_VALIDATOR,
                vol.Optional(CONF_IMPORT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="todo")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TaskPadOptionsFlow:
        return TaskPadOptionsFlow()


class TaskPadOptionsFlow(OptionsFlow):
    """Let topic prefix, log path, and default interval be changed later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TOPIC_PREFIX,
                    default=current.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX),
                ): str,
                vol.Required(
                    CONF_LOG_PATH,
                    default=current.get(CONF_LOG_PATH, DEFAULT_LOG_FILENAME),
                ): str,
                vol.Required(
                    CONF_DEFAULT_INTERVAL,
                    default=current.get(CONF_DEFAULT_INTERVAL, DEFAULT_INTERVAL_DAYS),
                ): INTERVAL_VALIDATOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
