"""The TaskPad integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_TASK,
    CONF_TOPIC_PREFIX,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
    SERVICE_COMPLETE,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .manager import TaskPadManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
SERVICE_COMPLETE_SCHEMA = vol.Schema({vol.Required(ATTR_TASK): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the taskpad.complete service."""

    async def handle_complete(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.async_complete(
                call.data[ATTR_TASK], source="service"
            )

    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE, handle_complete, schema=SERVICE_COMPLETE_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TaskPad from a config entry."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("The MQTT integration is not available")

    manager = TaskPadManager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up when the integration is removed: storage and retained topic."""
    await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()
    prefix = entry.data.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
    try:
        await mqtt.async_publish(hass, f"{prefix}/tasks", "", qos=1, retain=True)
    except Exception:  # noqa: BLE001 - MQTT may already be gone
        _LOGGER.debug("Could not clear retained task topic during removal")
