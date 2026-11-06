"""Window recommendation sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, REC_CLOSE, REC_OPEN, REC_STATES
from .entity import SmartifyHeatingEntity

ICONS = {REC_OPEN: "mdi:window-open-variant", REC_CLOSE: "mdi:window-closed-variant"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    ctrl = hass.data[DOMAIN]["controller"]
    entities: list[SensorEntity] = [TotalRecommendation(ctrl)]
    entities += [RoomRecommendation(ctrl, r) for r in ctrl.data["rooms"] if r["windows"]]
    add(entities)


def _round(v):
    return None if v is None else round(v, 1)


class RoomRecommendation(SmartifyHeatingEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = REC_STATES
    _attr_translation_key = "recommendation"

    def __init__(self, ctrl, room) -> None:
        super().__init__(ctrl, room, "recommendation", "sensor", f"{room['slug']}_fenster_empfehlung")
        self._attr_name = f"{room['name']} Fenster Empfehlung"

    @property
    def _rt(self):
        return self.ctrl.runtime.get(self.room["id"])

    @property
    def native_value(self) -> str | None:
        return self._rt.rec if self._rt else None

    @property
    def icon(self) -> str:
        return ICONS.get(self.native_value, "mdi:window-shutter-open")

    @property
    def extra_state_attributes(self) -> dict:
        rt = self._rt
        v = self.ctrl.room_values(self.room)
        return {
            "grund": rt.reason if rt else None,
            "innen": _round(v["inside"]),
            "soll": _round(v["target"]),
            "aussen": _round(v["outside"]),
            "fenster_offen": rt.window_open if rt else None,
            "offen_seit": rt.open_since.isoformat() if rt and rt.open_since else None,
            "pause_bis": rt.cooldown_until.isoformat() if rt and rt.cooldown_until else None,
            "raum_id": self.room["id"],
        }


class TotalRecommendation(SmartifyHeatingEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = REC_STATES
    _attr_translation_key = "recommendation"

    def __init__(self, ctrl) -> None:
        super().__init__(ctrl, None, "recommendation", "sensor", "fenster_empfehlung_gesamt")
        self._attr_name = "Fenster Empfehlung Gesamt"

    @property
    def native_value(self) -> str:
        return self.ctrl.aggregate()

    @property
    def icon(self) -> str:
        return ICONS.get(self.native_value, "mdi:window-shutter-open")

    @property
    def extra_state_attributes(self) -> dict:
        names = {r["id"]: r["name"] for r in self.ctrl.data["rooms"]}
        by = lambda s: [names[k] for k, rt in self.ctrl.runtime.items() if rt.rec == s and k in names]
        return {"oeffnen": by(REC_OPEN), "schliessen": by(REC_CLOSE)}
