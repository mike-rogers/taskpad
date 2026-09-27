"""Config flow for TaskPad, including zeroconf discovery and adoption."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.network import get_url
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .adoption import async_push_config
from .const import (
    CONF_DEFAULT_INTERVAL,
    CONF_DEVICE_HOST,
    CONF_IMPORT_ENTITY,
    CONF_LOG_PATH,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_URI,
    CONF_MQTT_USERNAME,
    CONF_TOPIC_PREFIX,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_LOG_FILENAME,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

INTERVAL_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=1, max=3650))


def _guess_mqtt_uri(hass: HomeAssistant) -> str:
    """Best-effort default broker URI: HA's own address, port 1883.

    Prefer the raw IP — the device cannot resolve .local mDNS names.
    """
    try:
        if (ip := getattr(hass.config.api, "local_ip", None)):
            return f"mqtt://{ip}:1883"
    except Exception:  # noqa: BLE001
        pass
    try:
        host = urlparse(get_url(hass, allow_external=False)).hostname
        if host and not host.endswith(".local"):
            return f"mqtt://{host}:1883"
    except Exception:  # noqa: BLE001 - a default is never worth failing over
        pass
    return "mqtt://192.168.1.100:1883"


def _broker_schema(hass: HomeAssistant, current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_MQTT_URI,
                default=current.get(CONF_MQTT_URI, _guess_mqtt_uri(hass)),
            ): str,
            vol.Required(
                CONF_MQTT_USERNAME, default=current.get(CONF_MQTT_USERNAME, "")
            ): str,
            vol.Required(
                CONF_MQTT_PASSWORD, default=current.get(CONF_MQTT_PASSWORD, "")
            ): str,
        }
    )


class TaskPadConfigFlow(ConfigFlow, domain=DOMAIN):
    """Manual setup, plus zeroconf discovery with credential push."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        # ZeroconfServiceInfo.host was removed from HA; ip_address is current.
        host = str(
            getattr(discovery_info, "ip_address", None)
            or getattr(discovery_info, "host", "")
        )
        device_id = discovery_info.properties.get("id") or discovery_info.name
        await self.async_set_unique_id(device_id)

        # Already set up (single entry): remember the device's address for
        # re-adoption from the options menu, then bow out.
        if existing := self._async_current_entries():
            entry = existing[0]
            if entry.data.get(CONF_DEVICE_HOST) != host:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_DEVICE_HOST: host}
                )
                _LOGGER.info("TaskPad discovered at %s; host stored", host)
            return self.async_abort(reason="already_configured")

        self._host = host
        self.context["title_placeholders"] = {"name": f"TaskPad ({host})"}
        return await self.async_step_adopt()

    async def async_step_adopt(self, user_input: dict[str, Any] | None = None):
        """Push broker credentials to a discovered, unprovisioned device."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await async_push_config(
                    self.hass,
                    self._host,
                    user_input[CONF_MQTT_URI],
                    user_input[CONF_MQTT_USERNAME],
                    user_input[CONF_MQTT_PASSWORD],
                )
            except Exception:  # noqa: BLE001 - surfaced as a form error
                _LOGGER.exception("Adoption push to %s failed", self._host)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="TaskPad",
                    data={
                        CONF_DEVICE_HOST: self._host,
                        CONF_TOPIC_PREFIX: DEFAULT_TOPIC_PREFIX,
                        CONF_LOG_PATH: DEFAULT_LOG_FILENAME,
                        CONF_DEFAULT_INTERVAL: DEFAULT_INTERVAL_DAYS,
                        **user_input,
                    },
                )
        return self.async_show_form(
            step_id="adopt",
            data_schema=_broker_schema(self.hass, user_input or {}),
            errors=errors,
            description_placeholders={"host": self._host or "?"},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Manual setup without a discovered device (pre-M3 path)."""
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
    """Settings, plus (re-)adoption of the device."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(step_id="init", menu_options=["settings", "adopt"])

    async def async_step_settings(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )

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
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_adopt(self, user_input: dict[str, Any] | None = None):
        """Push broker credentials to the device (first time or rotation)."""
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            try:
                await async_push_config(
                    self.hass,
                    user_input[CONF_DEVICE_HOST],
                    user_input[CONF_MQTT_URI],
                    user_input[CONF_MQTT_USERNAME],
                    user_input[CONF_MQTT_PASSWORD],
                )
            except Exception:  # noqa: BLE001 - surfaced as a form error
                _LOGGER.exception(
                    "Adoption push to %s failed", user_input[CONF_DEVICE_HOST]
                )
                errors["base"] = "cannot_connect"
            else:
                # Keep host + credentials for future re-adoption.
                return self.async_create_entry(
                    data={**self.config_entry.options, **user_input}
                )

        source = user_input or current
        schema = _broker_schema(self.hass, source).extend(
            {
                vol.Required(
                    CONF_DEVICE_HOST, default=source.get(CONF_DEVICE_HOST, "")
                ): str,
            }
        )
        return self.async_show_form(
            step_id="adopt", data_schema=schema, errors=errors
        )
