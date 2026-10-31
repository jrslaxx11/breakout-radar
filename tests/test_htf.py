"""High tight flag (radar/htf.py): mástil, bandera y sus límites."""
from radar import htf
from radar.metrics import compute
from tests.test_stars import W, _lows_on_sma10, high_tide_flag, slow_extended

WP = {**W, "pole_days": 40}


def _m(n: int):
    return compute("HTF", _lows_on_sma10(high_tide_flag(n=n)), WP)


def test_detects_pole_and_flag():
    h = htf.evaluate(_m(255))
    assert h and h["kind"] == "clásica"
    assert h["pole"] >= 0.9 and h["pole_len"] <= 40 and h["flag_len"] == 20 and h["depth"] <= 0.25
    assert h["peak_date"] < h["flag_end"] and h["pole_date"] < h["peak_date"]
    assert "Mástil +" in h["text"] and "bandera de 20 sesiones" in h["text"]


def test_limits():
    m = _m(255)
    assert htf.evaluate(m, {"pole_min": 5.0}) is None             # mástil insuficiente
    assert htf.evaluate(m, {"depth_max": 0.05}) is None           # bandera demasiado profunda
    assert htf.evaluate(m, {"flag_max": 10}) is None              # bandera demasiado larga
    assert htf.evaluate(m, {"depth_classic": 0.05})["kind"] == "profunda"
    assert htf.evaluate(m, {"flag_min": 25})["kind"] == "en formación"
    assert htf.evaluate(_m(300)) is None                          # 65 sesiones: ya no es una bandera
    assert htf.evaluate(compute("SLOW", slow_extended(), WP)) is None
