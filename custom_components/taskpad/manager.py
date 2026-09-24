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
    EVENT_BLOCKED,
    EVENT_COMPLETED,
    INTERVAL_PATTERN,
    INTERVAL_UNIT_DAYS,
    STATUS_COMPLETED,
    STATUS_NEEDS_ACTION,
    STORAGE_KEY,
    STORAGE_VERSION,
    UNIT_TO_DAYS,
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
        self._unsubscribers: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Persistence and change notification

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.items = (data or {}).get("items", [])
        # Migrate items from before structured value/unit and prep_text.
        for item in self.items:
            if "interval_value" not in item:
                item["interval_value"] = item.get("interval_days") or (
                    self.default_interval
                )
                item["interval_unit"] = "days"
            item.setdefault("prep_text", "")

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
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                self.hass,
                f"{self.topic_prefix}/complete",
                self._async_handle_complete_msg,
            )
        )
        self._unsubscribers.append(
            await mqtt.async_subscribe(
                self.hass,
                f"{self.topic_prefix}/blocked",
                self._async_handle_blocked_msg,
            )
        )
        await self.async_publish_tasks()

    async def async_stop(self) -> None:
        while self._unsubscribers:
            self._unsubscribers.pop()()

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

    def _parse_interval(self, description: str | None) -> tuple[int, str] | None:
        """Legacy 'interval: N[dwmy]' in a description -> (value, unit)."""
        if not description:
            return None
        match = re.search(INTERVAL_PATTERN, description, re.IGNORECASE)
        if not match:
            return None
        value = int(match.group(1))
        char = match.group(2).lower()
        if char == "y":
            return (value * 365, "days")
        return (value, {"": "days", "d": "days", "w": "weeks", "m": "months"}[char])

    @staticmethod
    def _interval_days(value: int, unit: str) -> int:
        return int(value) * UNIT_TO_DAYS.get(unit, 1)

    def _new_item(
        self,
        summary: str,
        due: str | None,
        description: str,
        *,
        interval_value: int | None = None,
        interval_unit: str = "days",
        prep_text: str = "",
    ) -> dict[str, Any]:
        if interval_value is None:
            parsed = self._parse_interval(description)
            if parsed is not None:
                interval_value, interval_unit = parsed
            else:
                interval_value, interval_unit = self.default_interval, "days"
        return {
            "uid": str(uuid.uuid4()),
            "summary": summary,
            "status": STATUS_NEEDS_ACTION,
            "due": due,  # "YYYY-MM-DD" or None
            "description": description,
            "interval_value": int(interval_value),
            "interval_unit": interval_unit,
            "interval_days": self._interval_days(interval_value, interval_unit),
            "prep_text": prep_text or "",
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
            item["interval_value"], item["interval_unit"] = parsed
            item["interval_days"] = self._interval_days(*parsed)
        await self._async_save_and_notify()

    # ------------------------------------------------------------------
    # Typed create/edit used by the taskpad services and the custom card

    async def async_add_task(
        self,
        name: str,
        due: str,
        interval_value: int,
        interval_unit: str,
        prep_text: str,
    ) -> dict[str, Any]:
        item = self._new_item(
            name,
            due,
            "",
            interval_value=interval_value,
            interval_unit=interval_unit,
            prep_text=prep_text,
        )
        self.items.append(item)
        await self._async_save_and_notify()
        return item

    async def async_update_task(
        self,
        uid: str,
        name: str | None = None,
        due: str | None = None,
        interval_value: int | None = None,
        interval_unit: str | None = None,
        prep_text: str | None = None,
    ) -> None:
        item = self.get(uid)
        if item is None:
            _LOGGER.warning("update_task for unknown uid %s", uid)
            return
        if name is not None:
            item["summary"] = name
        if due is not None:
            item["due"] = due
        if interval_value is not None:
            item["interval_value"] = int(interval_value)
        if interval_unit is not None:
            item["interval_unit"] = interval_unit
        item["interval_days"] = self._interval_days(
            item["interval_value"], item["interval_unit"]
        )
        if prep_text is not None:
            item["prep_text"] = prep_text
        await self._async_save_and_notify()

    async def async_delete(self, uids: list[str]) -> None:
        remove = set(uids)
        parents_affected = {
            i["parent_uid"]
            for i in self.items
            if i["uid"] in remove and i.get("parent_uid")
        }
        self.items = [i for i in self.items if i["uid"] not in remove]
        # Deleting a prep task unblocks its parent if no other open prep remains.
        for parent_uid in parents_affected:
            parent = self.get(parent_uid)
            if (
                parent is not None
                and parent.get("blocked")
                and not self._open_preps(parent_uid)
            ):
                parent["blocked"] = False
        await self._async_save_and_notify()

    def _open_preps(self, parent_uid: str) -> list[dict[str, Any]]:
        return [
            i
            for i in self.items
            if i.get("parent_uid") == parent_uid
            and i["status"] == STATUS_NEEDS_ACTION
        ]

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

        # A prep task is one-shot: no successor; completing it unblocks its
        # parent (if the parent is still open).
        if item.get("one_shot"):
            note = ""
            parent = self.get(item.get("parent_uid") or "")
            if (
                parent is not None
                and parent["status"] == STATUS_NEEDS_ACTION
                and parent.get("blocked")
                and not self._open_preps(parent["uid"])
            ):
                parent["blocked"] = False
                note = f"; unblocked: {parent['summary']}"
            await self._async_save_and_notify()
            await self._async_log(
                f"completed prep: {item['summary']} (via {source}){note}"
            )
            self.hass.bus.async_fire(
                EVENT_COMPLETED,
                {
                    "uid": item["uid"],
                    "summary": item["summary"],
                    "next_due": None,
                    "prep": True,
                    "source": source,
                },
            )
            return None

        # Completing a blocked parent directly closes its orphaned prep tasks.
        closed_preps = ""
        for prep in self._open_preps(item["uid"]):
            prep["status"] = STATUS_COMPLETED
            prep["completed_at"] = now.isoformat()
            closed_preps = f"; auto-closed prep: {prep['summary']}"

        interval = int(item.get("interval_days") or self.default_interval)
        next_due = (now.date() + timedelta(days=interval)).isoformat()
        successor = self._new_item(
            item["summary"],
            next_due,
            item["description"],
            interval_value=item.get("interval_value") or interval,
            interval_unit=item.get("interval_unit") or "days",
            prep_text=item.get("prep_text") or "",
        )
        self.items.append(successor)

        await self._async_save_and_notify()
        await self._async_log(
            f"completed: {item['summary']}"
            f" (next due {next_due}, interval {interval}d, via {source})"
            f"{closed_preps}"
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
    # Blocking: create a linked one-shot prep task

    async def async_block(self, task: str, source: str) -> dict[str, Any] | None:
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
            _LOGGER.warning("Block for unknown task %r (source: %s)", task, source)
            return None
        if item.get("one_shot"):
            _LOGGER.warning("Refusing to block prep task %r", item["summary"])
            return None
        if item.get("blocked") and self._open_preps(item["uid"]):
            _LOGGER.debug("Task %r already blocked", item["summary"])
            return None

        now = dt_util.now()
        prep = {
            "uid": str(uuid.uuid4()),
            "summary": item.get("prep_text") or f"Prep: {item['summary']}",
            "status": STATUS_NEEDS_ACTION,
            "due": now.date().isoformat(),
            "description": f"One-shot prerequisite for: {item['summary']}",
            "interval_days": None,
            "interval_value": 1,
            "interval_unit": "days",
            "prep_text": "",
            "one_shot": True,
            "parent_uid": item["uid"],
            "created_at": now.isoformat(),
            "completed_at": None,
        }
        self.items.append(prep)
        item["blocked"] = True

        await self._async_save_and_notify()
        await self._async_log(
            f"blocked: {item['summary']} -> created prep task (via {source})"
        )
        self.hass.bus.async_fire(
            EVENT_BLOCKED,
            {
                "uid": item["uid"],
                "summary": item["summary"],
                "prep_uid": prep["uid"],
                "source": source,
            },
        )
        return prep

    # ------------------------------------------------------------------
    # Metadata for the entity attributes / custom card

    def task_attributes(self) -> list[dict[str, Any]]:
        open_items = [
            i for i in self.items if i["status"] == STATUS_NEEDS_ACTION
        ]
        open_items.sort(key=lambda i: i["due"] or "9999-99-99")
        return [
            {
                "uid": i["uid"],
                "name": i["summary"],
                "due": i["due"],
                "interval_value": i.get("interval_value"),
                "interval_unit": i.get("interval_unit"),
                "prep_text": i.get("prep_text") or "",
                "blocked": bool(i.get("blocked")),
                "prep": bool(i.get("one_shot")),
                "parent_uid": i.get("parent_uid"),
            }
            for i in open_items
        ]

    # ------------------------------------------------------------------
    # MQTT

    def _task_from_payload(self, msg: mqtt.ReceiveMessage) -> str | None:
        try:
            return json.loads(msg.payload)["task_id"]
        except (ValueError, KeyError, TypeError):
            _LOGGER.warning("Bad payload on %s: %r", msg.topic, msg.payload)
            return None

    async def _async_handle_complete_msg(self, msg: mqtt.ReceiveMessage) -> None:
        if (task := self._task_from_payload(msg)) is not None:
            await self.async_complete(task, source="device")

    async def _async_handle_blocked_msg(self, msg: mqtt.ReceiveMessage) -> None:
        if (task := self._task_from_payload(msg)) is not None:
            await self.async_block(task, source="device")

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
            [
                {
                    "id": i["uid"],
                    "name": i["summary"],
                    "due": i["due"],
                    "blocked": bool(i.get("blocked")),
                }
                for i in upcoming
            ]
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
