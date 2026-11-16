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


def test_deep_flag_far_from_its_level_stays_in_base():
    """Un HTF a más del 12% de su nivel sigue EN BASE (su regla admite corregir hasta un 35%), no descartado."""
    from radar import breakouts as bo
    from radar.config import Config
    S = Config.load().settings
    df = _lows_on_sma10(high_tide_flag(n=255)).copy()
    top = df["High"].iloc[200:236].max()
    c = top * 0.80
    df.iloc[-6:] = [[c, c * 1.01, c * 0.99, c, 1e6]] * 6
    m = compute("HTF", df, WP)
    h = htf.evaluate(m)
    assert h and h["kind"] == "clásica" and 1 - m.C / m.P > S["breakout"]["base_max_dist"]
    plain = bo.classify(m, 50e6, m.C, S["breakout"], S["filters"])
    withh = bo.classify(m, 50e6, m.C, S["breakout"], S["filters"], {**htf.DEFAULTS, **S["htf"]})
    assert plain.state == bo.DISCARDED
    assert withh.state == bo.BASE and "dentro de la bandera" in withh.why


def test_no_chase_when_the_trigger_is_more_than_one_adr_above_the_level():
    from radar import qullamaggie as qm
    m = _m(255)
    m.C, m.high = m.P * 1.02, m.P * (1 + 2 * m.adr_pct)      # cierra cerca del nivel tras un máximo muy por encima
    q = qm.evaluate(m, "TEMPRANA", {"light": "verde"})
    assert q["trigger"] is None and "perseguir" in q["entry_note"]
    m.high = m.P * 1.03
    assert qm.evaluate(m, "TEMPRANA", {"light": "verde"})["trigger"] == m.high
