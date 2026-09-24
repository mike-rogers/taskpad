"""Task storage, scheduling, history, and MQTT plumbing for TaskPad."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEFAULT_INTERVAL,
    CONF_IMPORT_ENTITY,
    CONF_LOG_PATH,
    CONF_TOPIC_PREFIX,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_LOG_FILENAME,
    DEFAULT_TOPIC_PREFIX,
    EVENT_COMPLETED,
    INTERVAL_PATTERN,
    INTERVAL_UNIT_DAYS,
    STATUS_COMPLETED,
    STATUS_NEEDS_ACTION,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class TaskPadManager:
    """Owns the task list, the history log, and the MQTT contract."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        conf = {**entry.data, **entry.options}
        self.topic_prefix: str = conf.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
        self.default_interval: int = int(
            conf.get(CONF_DEFAULT_INTERVAL, DEFAULT_INTERVAL_DAYS)
        )
        log_path: str = conf.get(CONF_LOG_PATH, DEFAULT_LOG_FILENAME)
        self.log_path = (
            log_path if os.path.isabs(log_path) else hass.config.path(log_path)
        )
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.items: list[dict[str, Any]] = []
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Persistence and change notification

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.items = (data or {}).get("items", [])

    async def _async_save_and_notify(self) -> None:
        await self._store.async_save({"items": self.items})
        for listener in self._listeners:
            listener()
        await self.async_publish_tasks()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    # ------------------------------------------------------------------
    # Lifecycle

    async def async_start(self) -> None:
        if self.entry.data.get(CONF_IMPORT_ENTITY) and not self.items:
            await self._async_import(self.entry.data[CONF_IMPORT_ENTITY])
        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            f"{self.topic_prefix}/complete",
            self._async_handle_complete_msg,
        )
        await self.async_publish_tasks()

    async def async_stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # ------------------------------------------------------------------
    # Import from an existing to-do entity (one-time)

    async def _async_import(self, entity_id: str) -> None:
        try:
            response = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": entity_id, "status": STATUS_NEEDS_ACTION},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001 - import is best-effort
            _LOGGER.exception("Import from %s failed", entity_id)
            return
        imported = (response or {}).get(entity_id, {}).get("items", [])
        for item in imported:
            due = str(item.get("due") or "")[:10] or None
            self.items.append(
                self._new_item(
                    item.get("summary", "?"), due, item.get("description") or ""
                )
            )
        _LOGGER.info("Imported %d open items from %s", len(imported), entity_id)
        await self._async_save_and_notify()

    # ------------------------------------------------------------------
    # Item helpers

    def get(self, uid: str) -> dict[str, Any] | None:
        return next((i for i in self.items if i["uid"] == uid), None)

    def _parse_interval(self, description: str | None) -> int | None:
        if not description:
            return None
        match = re.search(INTERVAL_PATTERN, description, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1)) * INTERVAL_UNIT_DAYS[match.group(2).lower()]

    def _new_item(
        self, summary: str, due: str | None, description: str
    ) -> dict[str, Any]:
        interval = self._parse_interval(description)
        if interval is None:
            interval = self.default_interval
            suffix = f"interval: {interval}"
            description = f"{description}\n{suffix}" if description else suffix
        return {
            "uid": str(uuid.uuid4()),
            "summary": summary,
            "status": STATUS_NEEDS_ACTION,
            "due": due,  # "YYYY-MM-DD" or None
            "description": description,
            "interval_days": interval,
            "created_at": dt_util.now().isoformat(),
            "completed_at": None,
        }

    # ------------------------------------------------------------------
    # CRUD used by the todo entity

    async def async_create(
        self, summary: str, due: str | None, description: str | None
    ) -> dict[str, Any]:
        item = self._new_item(summary, due, description or "")
        self.items.append(item)
        await self._async_save_and_notify()
        return item

    async def async_update_fields(
        self,
        uid: str,
        summary: str,
        due: str | None,
        description: str,
        status: str,
    ) -> None:
        item = self.get(uid)
        if item is None:
            _LOGGER.warning("Update for unknown item %s", uid)
            return
        item["summary"] = summary
        item["due"] = due
        item["description"] = description
        item["status"] = status
        parsed = self._parse_interval(description)
        if parsed is not None:
            item["interval_days"] = parsed
        await self._async_save_and_notify()

    async def async_delete(self, uids: list[str]) -> None:
        remove = set(uids)
        self.items = [i for i in self.items if i["uid"] not in remove]
        await self._async_save_and_notify()

    # ------------------------------------------------------------------
    # Completion: close item, create successor, log, fire event

    async def async_complete(self, task: str, source: str) -> dict[str, Any] | None:
        item = next(
            (
                i
                for i in self.items
                if i["status"] == STATUS_NEEDS_ACTION
                and task in (i["uid"], i["summary"])
            ),
            None,
        )
        if item is None:
            _LOGGER.warning("Completion for unknown task %r (source: %s)", task, source)
            return None

        now = dt_util.now()
        item["status"] = STATUS_COMPLETED
        item["completed_at"] = now.isoformat()

        interval = int(item.get("interval_days") or self.default_interval)
        next_due = (now.date() + timedelta(days=interval)).isoformat()
        successor = self._new_item(item["summary"], next_due, item["description"])
        successor["interval_days"] = interval
        self.items.append(successor)

        await self._async_save_and_notify()
        await self._async_log(
            f"completed: {item['summary']}"
            f" (next due {next_due}, interval {interval}d, via {source})"
        )
        self.hass.bus.async_fire(
            EVENT_COMPLETED,
            {
                "uid": item["uid"],
                "summary": item["summary"],
                "next_due": next_due,
                "source": source,
            },
        )
        return successor

    # ------------------------------------------------------------------
    # MQTT

    async def _async_handle_complete_msg(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            task = json.loads(msg.payload)["task_id"]
        except (ValueError, KeyError, TypeError):
            _LOGGER.warning("Bad payload on %s: %r", msg.topic, msg.payload)
            return
        await self.async_complete(task, source="device")

    async def async_publish_tasks(self) -> None:
        upcoming = sorted(
            (
                i
                for i in self.items
                if i["status"] == STATUS_NEEDS_ACTION and i["due"]
            ),
            key=lambda i: i["due"],
        )
        payload = json.dumps(
            [{"id": i["uid"], "name": i["summary"], "due": i["due"]} for i in upcoming]
        )
        try:
            await mqtt.async_publish(
                self.hass, f"{self.topic_prefix}/tasks", payload, qos=1, retain=True
            )
        except Exception:  # noqa: BLE001 - broker may be briefly unavailable
            _LOGGER.exception("Could not publish task list")

    # ------------------------------------------------------------------
    # History log

    async def _async_log(self, message: str) -> None:
        line = f"{dt_util.now().strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n"

        def write() -> None:
            with open(self.log_path, "a", encoding="utf-8") as file:
                file.write(line)

        try:
            await self.hass.async_add_executor_job(write)
        except OSError:
            _LOGGER.exception("Could not append to history log %s", self.log_path)
