"""Tests der Fensterlogik ohne Home Assistant."""
import importlib.util
import pathlib
import sys
import unittest

_path = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "smartify_heating" / "logic.py"
_spec = importlib.util.spec_from_file_location("shc_logic", _path)
L = importlib.util.module_from_spec(_spec)
sys.modules["shc_logic"] = L
_spec.loader.exec_module(L)

P = {
    "open_above": 1.0, "open_min_delta": 2.0, "hysteresis": 0.3, "close_margin": 0.3,
    "close_delta": 1.0, "max_vent_min": 15, "cooldown_min": 30, "hold_min": 5,
    "shutdown_delay_s": 60, "restore_delay_s": 30,
}


def ev(**kw):
    base = dict(inside=22.0, target=22.0, outside=5.0, window_open=False, open_seconds=0,
                cooling=False, prev_state=L.REC_NONE, prev_age_s=9999, cooldown_left_s=0, p=P)
    base.update(kw)
    return L.evaluate(**base)


class Recommendation(unittest.TestCase):
    def test_in_setpoint_no_action(self):
        self.assertEqual(ev(inside=22.5).state, L.REC_NONE)

    def test_half_kelvin_over_is_not_open(self):
        # Bisheriges Verhalten (Bad 23,5 / Soll 23) hat bereits Öffnen empfohlen – jetzt nicht mehr
        self.assertEqual(ev(inside=23.5, target=23.0).state, L.REC_NONE)

    def test_open_when_warm_and_cold_outside(self):
        r = ev(inside=23.1)
        self.assertEqual((r.state, r.reason), (L.REC_OPEN, "zu_warm"))

    def test_no_open_when_outside_not_colder(self):
        self.assertEqual(ev(inside=24, outside=23).state, L.REC_NONE)

    def test_hysteresis_keeps_open(self):
        self.assertEqual(ev(inside=22.8, prev_state=L.REC_OPEN).state, L.REC_OPEN)
        self.assertEqual(ev(inside=22.6, prev_state=L.REC_OPEN).state, L.REC_NONE)

    def test_hold_time(self):
        r = ev(inside=23.5, prev_state=L.REC_NONE, prev_age_s=60)
        self.assertEqual((r.state, r.reason), (L.REC_NONE, "haltezeit"))

    def test_close_when_setpoint_reached(self):
        r = ev(inside=22.2, window_open=True, open_seconds=120)
        self.assertEqual((r.state, r.reason), (L.REC_CLOSE, "soll_erreicht"))

    def test_keep_open_in_gap(self):
        self.assertEqual(ev(inside=22.6, window_open=True, open_seconds=120).state, L.REC_NONE)

    def test_close_when_outside_warm(self):
        r = ev(inside=24, outside=23.5, window_open=True)
        self.assertEqual(r.reason, "aussen_zu_warm")

    def test_max_vent_and_cooldown(self):
        r = ev(inside=24, window_open=True, open_seconds=15 * 60)
        self.assertEqual((r.state, r.start_cooldown), (L.REC_CLOSE, True))
        self.assertEqual(ev(inside=24, cooldown_left_s=100).reason, "pause_nach_lueften")

    def test_no_max_vent_when_cooling(self):
        self.assertEqual(ev(inside=24, window_open=True, open_seconds=3600, cooling=True).state, L.REC_NONE)

    def test_closing_is_immediate_despite_hold(self):
        r = ev(inside=22.0, window_open=True, prev_state=L.REC_NONE, prev_age_s=5)
        self.assertEqual(r.state, L.REC_CLOSE)

    def test_missing_values(self):
        self.assertEqual(ev(inside=None).reason, "sensorwert_fehlt")
        self.assertEqual(ev(outside=None).reason, "sensorwert_fehlt")
        self.assertEqual(ev(outside=None, inside=22.0, window_open=True).state, L.REC_CLOSE)


class Modes(unittest.TestCase):
    def test_effective(self):
        self.assertEqual(L.effective_mode("off", "manual"), "off")
        self.assertEqual(L.effective_mode("manual", "global"), "manual")
        self.assertEqual(L.effective_mode("auto", "off"), "off")
        self.assertEqual(L.effective_mode("manual", "auto"), "auto")

    def test_shutdown(self):
        kw = dict(p=P, closed_seconds=0)
        self.assertIsNone(L.window_shutdown(mode="auto", window_open=True, open_seconds=30, paused=False, **kw))
        self.assertEqual(L.window_shutdown(mode="auto", window_open=True, open_seconds=61, paused=False, **kw), "pause")
        self.assertIsNone(L.window_shutdown(mode="manual", window_open=True, open_seconds=600, paused=False, **kw))
        self.assertEqual(L.window_shutdown(mode="manual", window_open=True, open_seconds=600, paused=True, **kw), "resume")
        self.assertEqual(L.window_shutdown(mode="auto", window_open=False, open_seconds=0, paused=True, p=P, closed_seconds=31), "resume")

    def test_aggregate(self):
        self.assertEqual(L.aggregate(["oeffnen", "schliessen"]), "schliessen")
        self.assertEqual(L.aggregate(["keine_aktion", "oeffnen"]), "oeffnen")
        self.assertEqual(L.aggregate([]), "keine_aktion")


if __name__ == "__main__":
    unittest.main()
