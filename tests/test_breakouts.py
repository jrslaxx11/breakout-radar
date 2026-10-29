"""Pruebas de la clasificación de rupturas con series construidas a mano."""
import numpy as np
import pandas as pd
import pytest

from radar import breakouts as bo
from radar.config import Config
from radar.metrics import compute

CFG = Config.load()
W, B, F = CFG.settings["windows"], CFG.settings["breakout"], CFG.settings["filters"]


def series(closes, vols=None, spread=0.01):
    """Construye OHLCV a partir de cierres: máximo/mínimo a ±spread del cierre."""
    closes = np.asarray(closes, dtype=float)
    vols = np.full(len(closes), 1_000_000.0) if vols is None else np.asarray(vols, dtype=float)
    idx = pd.bdate_range("2025-09-01", periods=len(closes))
    return pd.DataFrame({"Open": closes, "High": closes * (1 + spread), "Low": closes * (1 - spread),
                         "Close": closes, "Volume": vols}, index=idx)


def uptrend_with_base(n=260, base_len=25, base_level=100.0):
    """Tendencia alcista hasta `base_level` y después una base lateral estrecha."""
    up = np.linspace(50, base_level, n - base_len)
    base = base_level * (0.97 + 0.02 * np.sin(np.linspace(0, 6, base_len)))
    return np.concatenate([up, base])


def classify(df):
    m = compute("TEST", df, W)
    return bo.classify(m, 50e6, m.C, B, F), m


def test_confirmed_breakout_with_volume():
    c = uptrend_with_base()
    c[-1] = c[:-1][-60:].max() * 1.04          # cierra un 4% sobre la resistencia
    v = np.full(len(c), 1e6)
    v[-1] = 2.5e6                              # 2,5x volumen
    cl, m = classify(series(c, v))
    assert cl.state == bo.CONFIRMED, cl
    assert m.cross == 0


def test_early_breakout_without_volume():
    c = uptrend_with_base()
    c[-1] = c[:-1][-60:].max() * 1.03
    cl, _ = classify(series(c))
    assert cl.state == bo.EARLY


def test_pre_breakout_near_resistance():
    c = uptrend_with_base(base_len=30)
    c[-1] = c[:-1][-60:].max() * 0.975
    cl, _ = classify(series(c))
    assert cl.state == bo.PRE


def test_extended():
    c = uptrend_with_base()
    c[-1] = c[:-1][-60:].max() * 1.15
    cl, _ = classify(series(c))
    assert cl.state == bo.EXTENDED


def test_failed_breakout():
    c = uptrend_with_base()
    top = c[:-3][-60:].max()
    c[-3] = top * 1.03                         # cruza…
    c[-2] = top * 0.99
    c[-1] = top * 0.94                         # …y cae más de un 3% bajo el pivote
    cl, _ = classify(series(c))
    assert cl.state == bo.DISCARDED and "fallida" in cl.why


def test_illiquid_is_discarded():
    c = uptrend_with_base()
    m = compute("TEST", series(c), W)
    assert bo.classify(m, 1e6, m.C, B, F).state == bo.DISCARDED


def test_pinned_price_is_discarded():
    c = np.concatenate([np.linspace(50, 100, 200), np.full(60, 100.0)])
    m = compute("TEST", series(c, spread=0.001), W)
    assert bo.classify(m, 50e6, m.C, B, F).why.startswith("precio anclado")


def test_score_redistributes_missing_catalyst():
    c = uptrend_with_base()
    m = compute("TEST", series(c), W)
    with_zero = bo.score(m, bo.PRE, 0.9, 60e6, 0.0)
    missing = bo.score(m, bo.PRE, 0.9, 60e6, None)
    assert missing["total"] == pytest.approx(with_zero["total"] * 100 / 95, abs=0.01)
    assert 0 <= with_zero["total"] <= 100
