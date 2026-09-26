"""TaskPad device connectivity, driven by the MQTT availability topic."""

from __future__ import annotations

from homeassistant.components import mqtt
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .manager import TaskPadManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TaskPadConnectivity(entry)])


class TaskPadConnectivity(BinarySensorEntity):
    """on = the device holds its MQTT session (last-will handles offline)."""

    _attr_has_entity_name = True
    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._manager: TaskPadManager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_connectivity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="TaskPad",
            manufacturer="DIY",
            model='ESP32-C3 + ST7789 2.8"',
        )
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        @callback
        def message_received(msg: mqtt.ReceiveMessage) -> None:
            self._attr_is_on = msg.payload == "online"
            self.async_write_ha_state()

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass,
                f"{self._manager.topic_prefix}/availability",
                message_received,
            )
        )
