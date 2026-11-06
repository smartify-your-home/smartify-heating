"""Aggregated window state per room (any contact open = open)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import SmartifyHeatingEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    ctrl = hass.data[DOMAIN]["controller"]
    add([RoomWindow(ctrl, r) for r in ctrl.data["rooms"] if r["windows"]])


class RoomWindow(SmartifyHeatingEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, ctrl, room) -> None:
        super().__init__(ctrl, room, "window", "binary_sensor", f"{room['slug']}_fenster_offen")
        self._attr_name = "Fenster offen"

    @property
    def is_on(self) -> bool | None:
        rt = self.ctrl.runtime.get(self.room["id"])
        return rt.window_open if rt else None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "kontakte": self.room["windows"],
            "fensterabschaltung": self.room["id"] in self.ctrl.data["paused"],
        }
