"""Estrellas del setup (radar/stars.py) con series sintéticas de forma conocida."""
import numpy as np
import pandas as pd

from radar import qullamaggie as qm
from radar import stars
from radar.metrics import compute

W = {"pivot_lookback": 60, "base_min": 5, "cross_window": 5, "recent_highs": 3}


def high_tide_flag(n: int = 260, seed: int = 7) -> pd.DataFrame:
    """Subida lineal del 150% en 35 sesiones y flag estrecho de 12 sesiones sobre la SMA10, con volumen seco."""
    rng = np.random.default_rng(seed)
    c = np.empty(n)
    c[:200] = 20 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, 200)))
    up = 35
    c[200:200 + up] = c[199] * np.exp(np.linspace(0, np.log(2.5), up + 1)[1:])
    top = c[200 + up - 1]
    k = n - 200 - up
    c[200 + up:] = top * (0.94 + 0.02 * np.sin(np.linspace(0, 3, k)))   # flag que se estrecha
    c[-5:] = top * np.array([0.955, 0.952, 0.958, 0.954, 0.957])
    h = c * (1 + rng.uniform(0.03, 0.06, n))
    l = c * (1 - rng.uniform(0.03, 0.06, n))
    h[200 + up:] = np.minimum(h[200 + up:], top * 0.995)
    h[-3:], l[-3:] = c[-3:] * 1.012, c[-3:] * 0.988                       # tres velas muy estrechas
    v = np.full(n, 2e6)
    v[200:200 + up] = 6e6
    v[-5:] = 0.8e6
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


def slow_extended(n: int = 260, seed: int = 3) -> pd.DataFrame:
    """Valor lento (ADR ~1,5%) que se aleja de sus medias sin consolidar."""
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.006, n)))
    c[-10:] = c[-11] * np.exp(np.cumsum(np.full(10, 0.006)))
    h, l = c * 1.007, c * 0.993
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": np.full(n, 1e6)}, index=idx)


def _lows_on_sma10(df: pd.DataFrame) -> pd.DataFrame:
    """Hace que los mínimos de las 3 últimas sesiones toquen la SMA10 (apoyo en la media)."""
    s10 = df["Close"].rolling(10).mean().iloc[-1]
    df.iloc[-2, df.columns.get_loc("Low")] = s10 * 0.995
    return df


def test_high_tide_flag_is_top_rated():
    df = _lows_on_sma10(high_tide_flag())
    m = compute("HTF", df, W)
    r = stars.rate(m)
    assert r is not None and r["max"] == stars.MAX_POINTS
    assert r["pillars"]["lider"] == 20 and r["pillars"]["velocidad"] >= 7
    assert r["pillars"]["medias"] >= 9, r["items"]
    assert r["stars"] >= 4.5, (r["points"], r["items"])
    assert sum(i["pts"] for i in r["items"]) + sum(p["pts"] for p in r["penalties"]) == r["points"]


def test_slow_extended_scores_low():
    m = compute("SLOW", slow_extended(), W)
    r = stars.rate(m)
    assert r["stars"] <= 2.0, (r["points"], r["items"])
    assert r["pillars"]["velocidad"] == 0 and r["pillars"]["lider"] == 0


def test_steps_and_theme_bonus():
    assert stars.stars_for(66) == 5 and stars.stars_for(50) == 5 and stars.stars_for(49) == 4.5
    assert stars.stars_for(15) == 1.5 and stars.stars_for(14) == 1 and stars.stars_for(-6) == 1
    m = compute("HTF", _lows_on_sma10(high_tide_flag()), W)
    plain, hot = stars.rate(m), stars.rate(m, theme_hot=True)
    assert hot["stars"] == min(5.0, plain["chart_stars"] + 0.5) and hot["chart_stars"] == plain["chart_stars"]
    assert hot["theme_bonus"] == (plain["chart_stars"] < 5)


def test_setup_is_measured_the_day_before_the_breakout():
    """Si hoy rompe, la foto del setup es la de ayer: la vela de ruptura no estropea la compresión."""
    df = _lows_on_sma10(high_tide_flag())
    before = stars.rate(compute("HTF", df, W))
    lvl = compute("HTF", df, W).P
    nxt = df.index[-1] + pd.offsets.BDay(1)
    c = lvl * 1.06
    df.loc[nxt] = [lvl * 1.005, c * 1.01, lvl * 0.995, c, 9e6]
    m = compute("HTF", df, W)
    assert m.cross == 0
    after = stars.rate(m)
    assert after["points"] == before["points"], (before["items"], after["items"])


def test_qm_rules_follow_the_study():
    df = _lows_on_sma10(high_tide_flag())
    m = compute("HTF", df, W)
    q = qm.evaluate(m, "PRE-BREAKOUT", {"light": "verde"}, None, None)
    keys = [c["key"] for c in q["checks"]]
    assert "orderly" not in keys and set(qm.HARD) == {"leader", "adr", "prior_move", "base"}
    assert qm.DEFAULTS["base_max"] == 60
    move = next(c for c in q["checks"] if c["key"] == "prior_move")
    assert move["ok"] is True
    cut = qm.perf_cutoffs([m], 0.02)
    assert set(cut) == {"mom1", "mom3", "mom6"} and cut["mom3"] == m.mom3
