"""TaskPad firmware update entity.

installed_version comes from the device's retained taskpad/status message;
latest_version from firmware/version.txt next to the served binary
(staged by scripts/release_firmware.sh). Install publishes the download
URL to taskpad/ota; the device pulls, flashes the other OTA slot, and
reboots (bootloader rollback covers a bad image).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FIRMWARE_URL
from .manager import TaskPadManager

_LOGGER = logging.getLogger(__name__)

VERSION_FILE = Path(__file__).parent / "firmware" / "version.txt"

SCAN_INTERVAL_SUPPORT = True  # polled: re-reads version.txt periodically


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TaskPadUpdate(entry)], update_before_add=True)


class TaskPadUpdate(UpdateEntity):
    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_should_poll = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._manager: TaskPadManager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_firmware"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="TaskPad",
            manufacturer="DIY",
            model='ESP32-C3 + ST7789 2.8"',
        )
        self._attr_installed_version = None
        self._attr_latest_version = None

    async def async_added_to_hass(self) -> None:
        @callback
        def status_received(msg: mqtt.ReceiveMessage) -> None:
            try:
                self._attr_installed_version = json.loads(msg.payload).get(
                    "version"
                )
            except ValueError:
                _LOGGER.warning("Bad status payload: %r", msg.payload)
                return
            self.async_write_ha_state()

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass,
                f"{self._manager.topic_prefix}/status",
                status_received,
            )
        )

    async def async_update(self) -> None:
        def read_version() -> str | None:
            # Both the marker and the binary must exist: a git/HACS install
            # tracks version.txt but not the 1.7MB taskpad.bin, and we must
            # not advertise an update whose download would 404.
            try:
                if not (VERSION_FILE.parent / "taskpad.bin").is_file():
                    return None
                return VERSION_FILE.read_text(encoding="utf-8").strip() or None
            except OSError:
                return None

        self._attr_latest_version = await self.hass.async_add_executor_job(
            read_version
        )

    async def async_install(
        self, version: str | None, backup: bool, **kwargs
    ) -> None:
        host = getattr(self.hass.config.api, "local_ip", None)
        port = getattr(self.hass.config.api, "port", 8123)
        if not host:
            _LOGGER.error("Cannot determine HA's local IP for the OTA URL")
            return
        url = f"http://{host}:{port}{FIRMWARE_URL}"
        _LOGGER.info("Requesting device OTA from %s", url)
        await mqtt.async_publish(
            self.hass,
            f"{self._manager.topic_prefix}/ota",
            json.dumps({"url": url}),
            qos=1,
            retain=False,
        )
