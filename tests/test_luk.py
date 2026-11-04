"""Sistema de Martin Luk (radar/luk.py) y calendario de EE. UU. (radar/calendar_us.py), con datos sintéticos."""
from datetime import date

import numpy as np
import pandas as pd

from radar import calendar_us, luk


def _df(closes, spread=0.025, vol=None, opens=None):
    c = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2025-06-02", periods=len(c))
    v = np.full(len(c), 1e6) if vol is None else np.asarray(vol, dtype=float)
    o = c if opens is None else np.asarray(opens, dtype=float)
    return pd.DataFrame({"Open": o, "High": np.maximum(c, o) * (1 + spread), "Low": np.minimum(c, o) * (1 - spread),
                         "Close": c, "Volume": v}, index=idx)


def _trend_then(pull, n0=100):
    """n0 sesiones de subida suave (+0,6%/día), un tramo fuerte de 15 (+2,5%/día) y el retroceso `pull`."""
    c = list(50 * np.cumprod(np.full(n0, 1.006)))
    for _ in range(15):
        c.append(c[-1] * 1.025)
    for r in pull:
        c.append(c[-1] * (1 + r))
    return c


def _last(df):
    P = luk.prepare(df)
    return luk.analyze(P, P["n"] - 1)


# ---------------------------------------------------------------- indicadores
def test_ema_seeded_with_sma():
    x = np.arange(1, 31, dtype=float)
    e = luk.ema(x, 9)
    assert np.isnan(e[:8]).all() and e[8] == np.mean(x[:9])
    a = 2 / 10
    assert abs(e[9] - (a * x[9] + (1 - a) * e[8])) < 1e-12
    # Con historia larga converge a la EMA sembrada con el primer valor (la de TradingView).
    y = np.random.default_rng(1).normal(0, 1, 600).cumsum() + 100
    ref = pd.Series(y).ewm(span=21, adjust=False).mean().to_numpy()
    assert abs(luk.ema(y, 21)[-1] / ref[-1] - 1) < 1e-6


def test_adr_pct_and_mean_prev():
    h = np.full(30, 105.0)
    l = np.full(30, 100.0)
    assert abs(luk.adr_pct(h, l, 20)[-1] - 0.05) < 1e-12 and np.isnan(luk.adr_pct(h, l, 20)[18])
    v = np.arange(1, 61, dtype=float)
    m = luk.mean_prev(v, 50)
    assert np.isnan(m[49]) and m[50] == np.mean(v[:50]) and m[59] == np.mean(v[9:59])   # sin la propia vela


def test_avwap():
    h, l, c = np.array([11.0, 12, 13, 14]), np.array([9.0, 10, 11, 12]), np.array([10.0, 11, 12, 13])
    v = np.array([100.0, 200, 300, 400])
    av = luk.avwap_series(h, l, c, v, 1)
    tp = (h + l + c) / 3
    assert np.isnan(av[0]) and av[1] == tp[1] and abs(av[3] - (tp[1:] * v[1:]).sum() / v[1:].sum()) < 1e-12
    P = luk.prepare(_df(_trend_then([-0.02] * 3)))
    assert abs(luk.avwap(P, 100, 110) - luk.avwap_series(P["h"], P["l"], P["c"], P["v"], 100)[110]) < 1e-9


def test_days_since_max():
    h = np.array([1, 5, 3, 5, 2, 1.0])
    assert luk.days_since_max(h, 5, 6) == (3, 2)        # empate: cuenta el más reciente
    assert luk.days_since_max(np.array([1, 2, 3.0]), 2, 3) == (2, 0)   # 0 = hoy


def test_episodic_pivot():
    c = np.full(80, 20.0)
    o = c.copy()
    v = np.full(80, 1e6)
    o[70], c[70:], v[70] = 22.5, 23.0, 3.5e6                # hueco +12,5% con 3,5 veces el volumen
    df = _df(c, vol=v, opens=o)
    P = luk.prepare(df)
    assert P["ep"][70] and not P["ep"][71] and P["last_ep"][79] == 70
    m50 = luk.mean_prev(v, 50)
    assert luk.is_ep(o, c, v, m50, 70, luk.DEFAULTS) and not luk.is_ep(o, c, v * 0 + 1e6, m50, 70, luk.DEFAULTS)
    a = luk.analyze(P, 79)
    assert a["anchor"] == "EP" and a["anchor_date"] == P["dates"][70] and a["anchor_since"] == 9


# ---------------------------------------------------------------- setups
def test_l1_pullback_and_recovery():
    a = _last(_df(_trend_then([-0.02, -0.025, -0.02, -0.015])))
    assert a["leader"] and a["setup"] == "L1" and a["days"] == 4
    assert 1 <= a["depth_adr"] <= 3 and a["close"] >= a["ema21"] and a["zone"]
    lv = luk.levels(a)
    assert abs(lv["entry"] - (a["high_today"] + 0.01)) < 1e-9 and abs(lv["stop"] / lv["entry"] - 0.985) < 1e-12
    assert abs(lv["size_pct"] - 0.25 / 1.5 * 100) < 1e-9 and lv["trigger"].startswith("Rotura del máximo")
    # Volumen del retroceso: no cuenta el día de recuperación (cierre sobre el máximo de ayer).
    c = _trend_then([-0.02, -0.025, -0.02, 0.05])
    v = np.full(len(c), 1e6)
    v[-1] = 5e6
    a2 = _last(_df(c, vol=v))
    assert a2["recovery"] and a2["vol_ratio"] is not None and a2["vol_ratio"] < 1.1


def test_l1b_undercut_then_l1():
    c = list(50 * np.cumprod(np.full(100, 1.006)))
    for _ in range(15):
        c.append(c[-1] * 1.012)                                  # tramo moderado: la EMA 21 queda cerca
    seq = c + list(np.array(c[-1]) * np.cumprod(np.full(6, 0.985)))
    a = _last(_df(seq))
    assert a["close"] < a["ema21"] and a["setup"] == "L1b", a["setup_why"]
    assert -0.75 <= (a["close"] - a["ema21"]) / (a["adr"] * a["close"]) < 0
    lv = luk.levels(a)
    assert lv["trigger"] == "Reclaim de la EMA 21" and abs(lv["entry"] - a["ema21"] - 0.01) < 1e-9
    a2 = _last(_df(seq + [a["ema21"] * 1.02]))                # al día siguiente cierra sobre la EMA 21
    assert a2["setup"] == "L1"


def test_rejections():
    assert _last(_df(_trend_then([])))["setup"] in (None, "L3")              # en máximos: sin retroceso
    deep = _last(_df(_trend_then([-0.05] * 6)))
    assert deep["setup"] not in luk.SETUPS                                  # corrección > 3 ADR o rota
    down = _last(_df(list(100 * np.cumprod(np.full(160, 0.995)))))
    assert not down["leader"] and down["why"].startswith("medias")
    assert _last(_df(_trend_then([-0.02] * 3)))["leader"]                    # sigue siendo líder
    P = luk.prepare(_df(_trend_then([-0.02] * 3)))
    assert luk.analyze(P, P["n"] - 1, scan_ok=False)["why"] == "no está en el escáner de momentum"


def test_l3_base():
    c = _trend_then([])
    top = c[-1]
    c += [top * x for x in (0.99, 1.0, 0.995, 1.002, 0.998, 1.0, 0.997, 1.001, 0.999, 1.0, 1.003)]
    a = _last(_df(c, spread=0.008))                             # el último día marca el máximo: no es L1
    assert a["days"] == 0 and a["setup"] == "L3" and a["base_range_adr"] <= 2
    lv = luk.levels(a)
    assert abs(lv["entry"] - a["base_hi"] - 0.01) < 1e-9 and "solo con stop <= 1,5%" in lv["trigger"]


def test_far_from_52w_high_unless_ep():
    c = list(100 * np.cumprod(np.full(130, 1.004)))
    c += list(np.array([c[-1]]) * np.cumprod(np.full(80, 0.985)))
    c += list(np.array([c[-1]]) * np.cumprod(np.full(40, 1.015)))
    a = _last(_df(c))
    assert a["dist52"] > 0.25 and not a["leader"] and "52 semanas" in a["why"]
    o = np.array(c)
    v = np.full(len(c), 1e6)
    o[-30], v[-30] = c[-31] * 1.12, 4e6                         # EP hace 29 sesiones: se perdona la distancia
    a2 = _last(_df(c, vol=v, opens=o))
    assert a2["ep60"] and "52 semanas" not in a2["why"]


# ---------------------------------------------------------------- salud, modo y ranking
def test_health_and_mode():
    up = luk.prepare(_df(_trend_then([])))
    down = luk.prepare(_df(list(100 * np.cumprod(np.full(140, 0.99)))))
    assert luk.health(up, up["n"] - 1) == "sano" and luk.health(down, down["n"] - 1) == "dañado"
    o = np.array(_trend_then([]))
    c = o.copy()
    o[-2] = c[-3] * 0.93                                     # hueco bajista de 7% (> ADR) hace 2 sesiones
    gapped = luk.prepare(_df(c, opens=o))
    assert luk.health(gapped, gapped["n"] - 1) == "dañado"
    assert luk.mode({"n": 100, "good": 51, "bad": 10}) == "LARGO"
    assert luk.mode({"n": 100, "good": 5, "bad": 90}) == "CORTO"
    assert luk.mode({"n": 100, "good": 50, "bad": 20}) == "NEUTRO"


def test_score_and_penalties():
    a = _last(_df(_trend_then([-0.02, -0.025, -0.02, -0.015])))
    s = luk.score(a, rs=0.9, theme_n=2, earn_sessions=None, earn_known=True)
    p = s["parts"]
    assert 0 <= s["score"] <= 100 and p["theme"] == 0.5 and s["mult"] == 1.0 and not s["flags"]
    s2 = luk.score(a, rs=0.9, theme_n=2, earn_sessions=3, earn_known=True)
    assert s2["mult"] == 0.8 and s2["score"] < s["score"] and "resultados en 3 sesiones" in s2["flags"]
    s3 = luk.score({**a, "wide_day": 0.05}, rs=0.9, theme_n=9, earn_sessions=None, earn_known=False)
    assert s3["mult"] == 0.9 and "requiere gatillo intradía" in s3["flags"] and "verificar resultados" in s3["flags"]
    assert s3["parts"]["theme"] == 1.0


def test_universe_check():
    ok, why, flags = luk.universe_check({"name": "Acme Corp", "source": "USA", "adr": False}, "Software", 5e9, 50, 50e6, 0.05)
    assert ok and not flags
    assert luk.universe_check({"name": "Alpha Acquisition Corp", "adr": False}, "Shell Companies", 5e8, 10, 50e6, 0.05)[1] == "SPAC"
    assert luk.universe_check({"name": "Foo Holdings", "adr": True}, "Software", 5e9, 50, 50e6, 0.05)[1] == "ADR extranjero"
    assert luk.universe_check({"name": "Foo Holdings", "adr": True}, "Software", 5e9, 50, 50e6, 0.05, {"include_adrs": True})[0]
    assert luk.universe_check({"name": "Big Income Fund", "adr": False}, None, 5e9, 50, 50e6, 0.05)[1] == "fondo"
    assert luk.universe_check({"name": "Tiny", "adr": False}, None, 1e8, 50, 50e6, 0.05)[1] == "capitalización"
    ok2, _, flags2 = luk.universe_check({"name": "NoCap", "adr": False}, None, None, 50, 50e6, 0.05)
    assert ok2 and flags2 == ["verificar capitalización"]
    assert luk.universe_check({"name": "Illiquid", "adr": False}, None, 5e9, 50, 9e6, 0.05)[1] == "valor negociado"
    assert luk.universe_check({"name": "Slow", "adr": False}, None, 5e9, 50, 50e6, 0.03)[1] == "ADR"


def test_us_calendar():
    h26 = calendar_us.holidays(2026)
    assert date(2026, 4, 3) in h26 and date(2026, 11, 26) in h26 and date(2026, 7, 3) in h26   # Viernes Santo, Acción de Gracias, 4 de julio en sábado
    assert date(2027, 6, 18) in calendar_us.holidays(2027) and date(2027, 12, 24) in calendar_us.holidays(2027)
    assert date(2027, 12, 31) not in calendar_us.holidays(2027)      # Año Nuevo 2028 en sábado: no se traslada
    assert calendar_us.sessions_until(date(2026, 11, 24), date(2026, 11, 30)) == 3   # mié, vie, lun (jueves festivo)
    assert calendar_us.sessions_until(date(2026, 11, 5), date(2026, 11, 5)) == 0
    assert calendar_us.sessions_until(date(2026, 11, 5), date(2026, 11, 4)) is None
    assert luk.earnings_sessions("2026-11-09", date(2026, 11, 5)) == 2


def test_history_stats_counts_and_coverage():
    frames = {f"S{i}": _df(_trend_then([-0.02, -0.025, -0.02, -0.015], n0=150 + i)) for i in range(6)}
    frames["DOWN"] = _df(list(100 * np.cumprod(np.full(269, 0.995))))
    last = {k: v.index[-1].date().isoformat() for k, v in frames.items()}
    st = luk.history_stats(frames, {k: True for k in frames}, {"backtest_days": 5}, 0.5,
                           {"min_mdv": 0, "min_price": 0},
                           [{"sym": "S0", "date": last["S0"], "verified": True}, {"sym": "X", "date": None, "verified": False}])
    assert st["days"] == 5 and len(st["daily"]) == 5 and st["max"] is not None
    cov = st["coverage"]
    assert cov["n"] == 1 and cov["rows"][1]["why"].startswith("sin fecha")
