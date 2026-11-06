"""Runtime controller: modes, window shutdown and window recommendations."""

from __future__ import annotations

import copy
import logging
import re
import uuid
from datetime import timedelta

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_GLOBALS,
    DEFAULT_PARAMS,
    GLOBAL_MODES,
    MODE_AUTO,
    MODE_GLOBAL,
    MODE_MANUAL,
    MODE_OFF,
    REC_NONE,
    ROOM_MODES,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .logic import aggregate, effective_mode, evaluate, window_shutdown

_LOGGER = logging.getLogger(__name__)
TICK = timedelta(seconds=15)
OPEN_STATES = {STATE_ON, "open", "true"}


def slugify(text: str) -> str:
    text = (text or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "raum"


def _float(hass: HomeAssistant, entity_id: str | None, attr: str | None = None) -> float | None:
    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if st is None:
        return None
    raw = st.attributes.get(attr) if attr else st.state
    if raw in (None, STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def normalize_config(data: dict | None) -> dict:
    """Validate and complete a stored/imported configuration."""
    data = copy.deepcopy(data or {})
    params = {**DEFAULT_PARAMS}
    for key, default in DEFAULT_PARAMS.items():
        try:
            params[key] = float((data.get("params") or {}).get(key, default))
        except (TypeError, ValueError):
            params[key] = default
    globals_ = {**DEFAULT_GLOBALS, **{k: str(v or "") for k, v in (data.get("globals") or {}).items() if k in DEFAULT_GLOBALS}}

    rooms, seen_ids, seen_slugs = [], set(), set()
    for raw in data.get("rooms") or []:
        if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
            continue
        rid = str(raw.get("id") or uuid.uuid4().hex[:8])
        while rid in seen_ids:
            rid = uuid.uuid4().hex[:8]
        slug = slugify(raw.get("slug") or raw.get("name"))
        base, n = slug, 2
        while slug in seen_slugs:
            slug, n = f"{base}_{n}", n + 1
        seen_ids.add(rid)
        seen_slugs.add(slug)
        windows = [w for w in (raw.get("windows") or []) if isinstance(w, str) and w]
        target = raw.get("target_temp")
        try:
            target = float(target) if target not in (None, "") else None
        except (TypeError, ValueError):
            target = None
        rooms.append({
            "id": rid,
            "name": str(raw["name"]).strip(),
            "slug": slug,
            "climate": str(raw.get("climate") or ""),
            "climate_cooling": str(raw.get("climate_cooling") or ""),
            "temperature_sensor": str(raw.get("temperature_sensor") or ""),
            "windows": list(dict.fromkeys(windows)),
            "target_temp": target,
            "icon": str(raw.get("icon") or ""),
        })

    mode = data.get("global_mode")
    room_modes = {
        r["id"]: (data.get("room_modes") or {}).get(r["id"], MODE_GLOBAL) for r in rooms
    }
    room_modes = {k: (v if v in ROOM_MODES else MODE_GLOBAL) for k, v in room_modes.items()}
    paused = {k: v for k, v in (data.get("paused") or {}).items() if k in room_modes and isinstance(v, str)}
    return {
        "global_mode": mode if mode in GLOBAL_MODES else MODE_AUTO,
        "room_modes": room_modes,
        "paused": paused,  # room_id -> hvac_mode vor der Fensterabschaltung
        "globals": globals_,
        "params": params,
        "rooms": rooms,
    }


class RoomRuntime:
    def __init__(self) -> None:
        self.rec = REC_NONE
        self.reason = "start"
        # Keine Haltezeit für die erste Bewertung nach dem Start
        self.rec_since = dt_util.utcnow() - timedelta(days=1)
        self.cooldown_until = None
        self.open_since = None
        self.closed_since = dt_util.utcnow()
        self.window_open = False


class HeatingController:
    """Single instance per config entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict = normalize_config(None)
        self.runtime: dict[str, RoomRuntime] = {}
        self._unsubs: list = []
        self._applied_modes: dict[str, str] = {}

    # ----- lifecycle -------------------------------------------------
    async def async_load(self) -> None:
        self.data = normalize_config(await self.store.async_load())
        self.runtime = {r["id"]: RoomRuntime() for r in self.data["rooms"]}

    async def async_save(self) -> None:
        await self.store.async_save(self.data)

    async def async_start(self) -> None:
        self._track()
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, TICK))
        # Fensterzustand initialisieren, dann Modi einmalig anwenden
        now = dt_util.utcnow()
        for room in self.data["rooms"]:
            rt = self.runtime[room["id"]]
            rt.window_open = self._window_open(room)
            if rt.window_open:
                rt.open_since = now
        await self._apply_all_modes(force=True)
        self._evaluate_all()

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def _track(self) -> None:
        ids = set()
        g = self.data["globals"]
        ids.update(x for x in (g["outside_sensor"], g["cooling_switch"]) if x)
        for room in self.data["rooms"]:
            ids.update(x for x in (room["climate"], room["climate_cooling"], room["temperature_sensor"]) if x)
            ids.update(room["windows"])
        if ids:
            self._unsubs.append(async_track_state_change_event(self.hass, list(ids), self._on_state))

    # ----- config ----------------------------------------------------
    def public_config(self) -> dict:
        return {k: copy.deepcopy(self.data[k]) for k in ("globals", "params", "rooms")}

    async def async_replace_config(self, new: dict) -> None:
        merged = {**self.data, **{k: new.get(k) for k in ("globals", "params", "rooms") if k in new}}
        self.data = normalize_config(merged)
        await self.async_save()

    # ----- modes -----------------------------------------------------
    def room_mode(self, room_id: str) -> str:
        return self.data["room_modes"].get(room_id, MODE_GLOBAL)

    def effective(self, room_id: str) -> str:
        return effective_mode(self.data["global_mode"], self.room_mode(room_id))

    async def async_set_global_mode(self, mode: str) -> None:
        if mode not in GLOBAL_MODES:
            return
        self.data["global_mode"] = mode
        await self.async_save()
        await self._apply_all_modes()
        self._notify()

    async def async_set_room_mode(self, room_id: str, mode: str) -> None:
        if mode not in ROOM_MODES or room_id not in self.data["room_modes"]:
            return
        self.data["room_modes"][room_id] = mode
        await self.async_save()
        await self._apply_all_modes()
        self._notify()

    def active_climate(self, room: dict) -> str:
        if self.cooling_active and room["climate_cooling"]:
            return room["climate_cooling"]
        return room["climate"]

    @property
    def cooling_active(self) -> bool:
        sw = self.data["globals"]["cooling_switch"]
        st = self.hass.states.get(sw) if sw else None
        return bool(st and st.state == STATE_ON)

    async def _set_hvac(self, entity_id: str, hvac_mode: str) -> None:
        st = self.hass.states.get(entity_id)
        if st is None or st.state == hvac_mode:
            return
        if hvac_mode not in (st.attributes.get("hvac_modes") or []):
            _LOGGER.warning("%s unterstützt hvac_mode %s nicht", entity_id, hvac_mode)
            return
        await self.hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": hvac_mode}, blocking=False
        )

    def _on_mode(self, entity_id: str) -> str:
        st = self.hass.states.get(entity_id)
        modes = (st.attributes.get("hvac_modes") if st else None) or []
        for m in ("heat", "cool", "heat_cool", "auto"):
            if m in modes:
                return m
        return "heat"

    async def _apply_all_modes(self, force: bool = False) -> None:
        """Modus nur bei Änderung anwenden – Benutzereingriffe am Thermostat bleiben sonst erhalten."""
        changed = False
        for room in self.data["rooms"]:
            climate = self.active_climate(room)
            if not climate:
                continue
            mode = self.effective(room["id"])
            if not force and self._applied_modes.get(room["id"]) == mode:
                continue
            st = self.hass.states.get(climate)
            if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue  # Thermostat noch nicht bereit -> beim nächsten Tick erneut
            self._applied_modes[room["id"]] = mode
            changed = True
            if mode == MODE_OFF:
                await self._set_hvac(climate, "off")
            elif mode == MODE_MANUAL:
                self.data["paused"].pop(room["id"], None)
                await self._set_hvac(climate, self._on_mode(climate))
            elif room["id"] not in self.data["paused"]:
                await self._set_hvac(climate, self._on_mode(climate))
        if changed:
            await self.async_save()

    # ----- evaluation ------------------------------------------------
    def _window_open(self, room: dict) -> bool:
        for w in room["windows"]:
            st = self.hass.states.get(w)
            if st and st.state in OPEN_STATES:
                return True
        return False

    def room_values(self, room: dict) -> dict:
        climate = self.active_climate(room)
        inside = _float(self.hass, room["temperature_sensor"]) if room["temperature_sensor"] else None
        if inside is None and climate:
            inside = _float(self.hass, climate, "current_temperature")
        target = _float(self.hass, climate, "temperature") if climate else None
        if target is None:
            target = room["target_temp"]
        return {
            "inside": inside,
            "target": target,
            "outside": _float(self.hass, self.data["globals"]["outside_sensor"]),
        }

    @callback
    def _on_state(self, event: Event) -> None:
        self.hass.async_create_task(self._async_update())

    async def _tick(self, _now) -> None:
        await self._apply_all_modes()
        await self._async_update()

    async def _async_update(self) -> None:
        now = dt_util.utcnow()
        for room in self.data["rooms"]:
            rt = self.runtime.setdefault(room["id"], RoomRuntime())
            is_open = self._window_open(room)
            if is_open and not rt.window_open:
                rt.open_since = now
            if not is_open and rt.window_open:
                rt.closed_since = now
                rt.open_since = None
            rt.window_open = is_open
            await self._window_shutdown(room, rt, now)
        self._evaluate_all()

    async def _window_shutdown(self, room: dict, rt: RoomRuntime, now) -> None:
        climate = self.active_climate(room)
        if not climate or not room["windows"]:
            return
        paused = room["id"] in self.data["paused"]
        action = window_shutdown(
            mode=self.effective(room["id"]),
            window_open=rt.window_open,
            open_seconds=(now - rt.open_since).total_seconds() if rt.open_since else 0,
            closed_seconds=(now - rt.closed_since).total_seconds() if rt.closed_since else 0,
            paused=paused,
            p=self.data["params"],
        )
        if action == "pause":
            st = self.hass.states.get(climate)
            prev = st.state if st and st.state not in ("off", STATE_UNAVAILABLE, STATE_UNKNOWN) else self._on_mode(climate)
            self.data["paused"][room["id"]] = prev
            await self._set_hvac(climate, "off")
            await self.async_save()
            _LOGGER.info("%s: Fensterabschaltung aktiv", room["name"])
        elif action == "resume":
            prev = self.data["paused"].pop(room["id"], None) or self._on_mode(climate)
            if self.effective(room["id"]) != MODE_OFF:
                await self._set_hvac(climate, prev)
            await self.async_save()
            _LOGGER.info("%s: Fensterabschaltung beendet", room["name"])

    def _evaluate_all(self) -> None:
        now = dt_util.utcnow()
        p = self.data["params"]
        cooling = self.cooling_active
        for room in self.data["rooms"]:
            rt = self.runtime.setdefault(room["id"], RoomRuntime())
            if not room["windows"]:
                continue  # Empfehlung nur für Räume mit Fensterkontakt
            v = self.room_values(room)
            res = evaluate(
                inside=v["inside"], target=v["target"], outside=v["outside"],
                window_open=rt.window_open,
                open_seconds=(now - rt.open_since).total_seconds() if rt.open_since else 0,
                cooling=cooling,
                prev_state=rt.rec,
                prev_age_s=(now - rt.rec_since).total_seconds(),
                cooldown_left_s=(rt.cooldown_until - now).total_seconds() if rt.cooldown_until else 0,
                p=p,
            )
            if res.start_cooldown and not rt.cooldown_until:
                rt.cooldown_until = now + timedelta(minutes=float(p["cooldown_min"]))
            if rt.cooldown_until and rt.cooldown_until <= now and not rt.window_open:
                rt.cooldown_until = None
            if res.state != rt.rec:
                rt.rec_since = now
            rt.rec, rt.reason = res.state, res.reason
        self._notify()

    def aggregate(self) -> str:
        return aggregate([rt.rec for rt in self.runtime.values()])

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
