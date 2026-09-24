"""TaskPad to-do list entity."""

from __future__ import annotations

from datetime import date

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATUS_COMPLETED, STATUS_NEEDS_ACTION
from .manager import TaskPadManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TaskPad todo platform."""
    async_add_entities([TaskPadTodoList(entry)])


class TaskPadTodoList(TodoListEntity):
    """The chore list, backed by the integration's own storage."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, entry: ConfigEntry) -> None:
        self._manager: TaskPadManager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_tasks"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="TaskPad",
            manufacturer="DIY",
            model='ESP32-C3 + ST7789 2.8"',
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._manager.async_add_listener(self.async_write_ha_state)
        )

    @property
    def extra_state_attributes(self) -> dict:
        # Consumed by the taskpad-card frontend.
        return {"tasks": self._manager.task_attributes()}

    @property
    def todo_items(self) -> list[TodoItem]:
        items = []
        for stored in self._manager.items:
            items.append(
                TodoItem(
                    uid=stored["uid"],
                    summary=stored["summary"],
                    status=(
                        TodoItemStatus.COMPLETED
                        if stored["status"] == STATUS_COMPLETED
                        else TodoItemStatus.NEEDS_ACTION
                    ),
                    due=date.fromisoformat(stored["due"]) if stored.get("due") else None,
                    description=stored.get("description") or None,
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        await self._manager.async_create(
            item.summary or "?",
            item.due.isoformat() if item.due else None,
            item.description,
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        stored = self._manager.get(item.uid) if item.uid else None
        # Ticking the checkbox runs the full completion flow: successor,
        # history line, event. This is deliberate; see MILESTONES.md (M1).
        if (
            stored is not None
            and stored["status"] == STATUS_NEEDS_ACTION
            and item.status == TodoItemStatus.COMPLETED
        ):
            await self._manager.async_complete(stored["uid"], source="home_assistant")
            return
        if item.uid is None:
            return
        await self._manager.async_update_fields(
            item.uid,
            summary=item.summary or "?",
            due=item.due.isoformat() if item.due else None,
            description=item.description or "",
            status=(
                STATUS_COMPLETED
                if item.status == TodoItemStatus.COMPLETED
                else STATUS_NEEDS_ACTION
            ),
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        await self._manager.async_delete(uids)
