"""Retrocesos al estilo Martin Luk (radar/luk.py)."""
import numpy as np
import pandas as pd

from radar import luk


def _df(closes, spread=0.025, vol=None):
    c = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2026-01-02", periods=len(c))
    v = np.full(len(c), 1e6) if vol is None else np.asarray(vol, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * (1 + spread), "Low": c * (1 - spread), "Close": c, "Volume": v}, index=idx)


def _trend_then(pull):
    """100 sesiones de subida (+0,6%/día), un tramo fuerte de 15 (+2,5%/día) y el retroceso `pull`."""
    c = list(50 * np.cumprod(np.full(100, 1.006)))
    for _ in range(15):
        c.append(c[-1] * 1.025)
    for r in pull:
        c.append(c[-1] * (1 + r))
    return c


def test_ema_matches_pandas():
    x = np.random.default_rng(1).normal(0, 1, 200).cumsum() + 100
    ref = pd.Series(x).ewm(span=21, adjust=False).mean().to_numpy()
    assert np.allclose(luk.ema(x, 21), ref)


def test_pullback_to_ema_then_reclaim():
    base = _trend_then([-0.02, -0.025, -0.02, -0.015])          # 4 sesiones de retroceso
    r = luk.evaluate(_df(base))
    assert r and r["state"] in ("en zona", "acercándose") and r["days"] == 4
    assert r["leg"] > 0.2 and r["ema9"] > r["ema21"] > r["ema50"]
    # Al día siguiente cierra sobre el máximo de ayer y la EMA 9: recupera.
    r2 = luk.evaluate(_df(base + [base[-1] * 1.05]))
    assert r2 and r2["state"] == "recupera" and r2["levels"]
    assert {k["key"] for k in r2["checks"]} == {"pull", "stack", "vol", "conf", "depth"}


def test_no_pullback_or_broken_trend():
    assert luk.evaluate(_df(_trend_then([]))) is None                       # en máximos: aún no retrocede
    assert luk.evaluate(_df(_trend_then([-0.06] * 6))) is None              # corrige demasiado
    down = list(100 * np.cumprod(np.full(140, 0.995)))
    assert luk.evaluate(_df(down)) is None                                  # sin tendencia
    assert luk.evaluate(_df(_trend_then([-0.02, -0.02]), spread=0.01)) is None  # ADR < 3%


def test_avwap_and_health():
    df = _df(_trend_then([-0.02] * 3))
    h, l, c, v = (df[k].to_numpy() for k in ("High", "Low", "Close", "Volume"))
    av = luk.avwap(h, l, c, v, 100)
    assert np.isnan(av[99]) and abs(av[100] - (h[100] + l[100] + c[100]) / 3) < 1e-9
    up, down = _df(_trend_then([])), _df(list(100 * np.cumprod(np.full(140, 0.99))))
    hh = luk.health({"A": up, "B": down, "C": up})
    assert (hh["n"], hh["good"], hh["bad"], hh["mixed"], hh["bad_syms"]) == (3, 2, 1, 0, ["B"])
