"""Pure logic for smartify Heizung (no Home Assistant imports, unit-testable)."""

from __future__ import annotations

from dataclasses import dataclass

REC_OPEN = "oeffnen"
REC_CLOSE = "schliessen"
REC_NONE = "keine_aktion"

MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_OFF = "off"
MODE_GLOBAL = "global"


@dataclass
class Result:
    state: str
    reason: str
    start_cooldown: bool = False


def effective_mode(global_mode: str, room_mode: str) -> str:
    """Globales Aus übersteuert alles; sonst gilt der Raummodus, 'global' folgt global."""
    if global_mode == MODE_OFF:
        return MODE_OFF
    if room_mode in (MODE_AUTO, MODE_MANUAL, MODE_OFF):
        return room_mode
    return global_mode if global_mode in (MODE_AUTO, MODE_MANUAL) else MODE_AUTO


def evaluate(
    *,
    inside: float | None,
    target: float | None,
    outside: float | None,
    window_open: bool,
    open_seconds: float,
    cooling: bool,
    prev_state: str,
    prev_age_s: float,
    cooldown_left_s: float,
    p: dict,
) -> Result:
    """Fensterempfehlung mit Gap/Hysterese.

    Öffnen:    Fenster zu, Ist >= Soll + open_above und innen-außen >= open_min_delta.
               Läuft bereits eine Öffnen-Empfehlung, gelten beide Schwellen minus hysteresis.
    Schließen: Fenster offen und Ist <= Soll + close_margin
               oder innen-außen < close_delta
               oder (nur Heizen) offen >= max_vent_min.
    Dazwischen: keine_aktion. Gap = open_above - close_margin.
    """
    if inside is None or target is None:
        return Result(REC_NONE, "sensorwert_fehlt")
    if outside is None and not window_open:
        # Ohne Außenwert kein Öffnen-Vorschlag; bei offenem Fenster gilt das Soll-Kriterium
        return Result(REC_NONE, "sensorwert_fehlt")

    excess = inside - target
    delta = None if outside is None else inside - outside

    if window_open:
        if excess <= p["close_margin"]:
            return Result(REC_CLOSE, "soll_erreicht")
        if delta is not None and delta < p["close_delta"]:
            return Result(REC_CLOSE, "aussen_zu_warm")
        max_vent = float(p.get("max_vent_min") or 0) * 60
        if not cooling and max_vent > 0 and open_seconds >= max_vent:
            return Result(REC_CLOSE, "lueftungsdauer", start_cooldown=True)
        return Result(REC_NONE, "lueften_ok")

    # Fenster geschlossen
    if cooldown_left_s > 0:
        return Result(REC_NONE, "pause_nach_lueften")

    hyst = p["hysteresis"] if prev_state == REC_OPEN else 0.0
    want_open = (
        delta is not None
        and excess >= p["open_above"] - hyst
        and delta >= p["open_min_delta"] - hyst
    )
    if want_open:
        new = Result(REC_OPEN, "zu_warm")
    elif excess >= p["open_above"]:
        new = Result(REC_NONE, "aussen_zu_warm")
    elif excess < 0:
        new = Result(REC_NONE, "zu_kalt")
    else:
        new = Result(REC_NONE, "im_soll")

    # Mindest-Haltezeit nur zwischen oeffnen <-> keine_aktion bei geschlossenem Fenster
    hold = float(p.get("hold_min") or 0) * 60
    if (
        new.state != prev_state
        and prev_state in (REC_OPEN, REC_NONE)
        and prev_age_s < hold
    ):
        return Result(prev_state, "haltezeit")
    return new


def window_shutdown(
    *,
    mode: str,
    window_open: bool,
    open_seconds: float,
    closed_seconds: float,
    paused: bool,
    p: dict,
) -> str | None:
    """Liefert 'pause', 'resume' oder None (Fensterabschaltung nur im Modus Auto)."""
    if mode != MODE_AUTO:
        return "resume" if paused and mode == MODE_MANUAL else None
    if window_open and not paused and open_seconds >= float(p["shutdown_delay_s"]):
        return "pause"
    if not window_open and paused and closed_seconds >= float(p["restore_delay_s"]):
        return "resume"
    return None


def aggregate(states: list[str]) -> str:
    if REC_CLOSE in states:
        return REC_CLOSE
    if REC_OPEN in states:
        return REC_OPEN
    return REC_NONE
