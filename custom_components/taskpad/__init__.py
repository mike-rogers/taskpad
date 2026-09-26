"""The TaskPad integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_TASK,
    CARD_URL,
    CONF_TOPIC_PREFIX,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
    INTERVAL_UNITS,
    SERVICE_ADD_TASK,
    SERVICE_BLOCK,
    SERVICE_COMPLETE,
    SERVICE_UPDATE_TASK,
    STORAGE_KEY,
    STORAGE_VERSION,
    VERSION,
)
from .manager import TaskPadManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.TODO, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

TASK_REF_SCHEMA = vol.Schema({vol.Required(ATTR_TASK): cv.string})
ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("due"): cv.date,
        vol.Required("interval_value"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("interval_unit"): vol.In(INTERVAL_UNITS),
        vol.Optional("prep_text", default=""): cv.string,
    }
)
UPDATE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("uid"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("due"): cv.date,
        vol.Optional("interval_value"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("interval_unit"): vol.In(INTERVAL_UNITS),
        vol.Optional("prep_text"): cv.string,
    }
)


def _managers(hass: HomeAssistant) -> list[TaskPadManager]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and serve the custom card."""

    async def handle_complete(call: ServiceCall) -> None:
        for manager in _managers(hass):
            await manager.async_complete(call.data[ATTR_TASK], source="service")

    async def handle_block(call: ServiceCall) -> None:
        for manager in _managers(hass):
            await manager.async_block(call.data[ATTR_TASK], source="service")

    async def handle_add_task(call: ServiceCall) -> None:
        for manager in _managers(hass):
            await manager.async_add_task(
                call.data["name"],
                call.data["due"].isoformat(),
                call.data["interval_value"],
                call.data["interval_unit"],
                call.data["prep_text"],
            )

    async def handle_update_task(call: ServiceCall) -> None:
        due = call.data.get("due")
        for manager in _managers(hass):
            await manager.async_update_task(
                call.data["uid"],
                name=call.data.get("name"),
                due=due.isoformat() if due else None,
                interval_value=call.data.get("interval_value"),
                interval_unit=call.data.get("interval_unit"),
                prep_text=call.data.get("prep_text"),
            )

    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE, handle_complete, schema=TASK_REF_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BLOCK, handle_block, schema=TASK_REF_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TASK, handle_add_task, schema=ADD_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_TASK, handle_update_task, schema=UPDATE_TASK_SCHEMA
    )

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL,
                str(Path(__file__).parent / "frontend" / "taskpad-card.js"),
                cache_headers=False,
            )
        ]
    )
    await _async_ensure_lovelace_resource(hass)
    return True


async def _async_ensure_lovelace_resource(hass: HomeAssistant) -> None:
    """Register the card in the Lovelace resource registry.

    Resources are awaited by the frontend before cards render; scripts
    injected via add_extra_js_url are not, and HA 2026.9 has no recovery
    for a custom card element that registers after first render.
    """
    versioned_url = f"{CARD_URL}?v={VERSION}"
    try:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None:
            _LOGGER.warning(
                "Lovelace resource registry unavailable (YAML-mode dashboards?); "
                "add %s as a module resource manually",
                versioned_url,
            )
            return
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
        existing = next(
            (
                item
                for item in resources.async_items()
                if str(item.get("url", "")).split("?")[0] == CARD_URL
            ),
            None,
        )
        if existing is None:
            await resources.async_create_item(
                {"res_type": "module", "url": versioned_url}
            )
            _LOGGER.info("Registered Lovelace resource %s", versioned_url)
        elif existing["url"] != versioned_url:
            await resources.async_update_item(
                existing["id"], {"res_type": "module", "url": versioned_url}
            )
            _LOGGER.info("Updated Lovelace resource to %s", versioned_url)
    except Exception:  # noqa: BLE001 - never let card plumbing block setup
        _LOGGER.exception(
            "Could not register the Lovelace resource; add %s as a module "
            "resource manually (Settings > Dashboards > Resources)",
            versioned_url,
        )


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
