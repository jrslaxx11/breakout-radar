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


def triangle(n=260, base_len=30, peak=100.0, drop=0.07):
    """Lateral, subida del 67% en 30 sesiones y triángulo: máximos descendentes y mínimos planos."""
    pre = np.full(n - base_len - 30, 60.0)
    rally = np.linspace(60, peak / 1.01, 30)
    t = np.arange(1, base_len + 1)
    top = peak * (1 - drop * t / base_len)          # resistencia descendente
    low = peak * 0.91
    wave = 0.5 + 0.5 * np.cos(t * 2 * np.pi / 6)      # toca la resistencia cada 6 sesiones
    return series(np.concatenate([pre, rally, low + (top / 1.01 - low) * wave]))


def flat_base(n=260, base_len=25, top=100.0):
    """Subida y base con techo plano: los máximos vuelven al mismo nivel cada 6 sesiones."""
    pre = np.full(n - base_len - 30, 60.0)
    rally = np.linspace(60, top / 1.01, 30)
    t = np.arange(1, base_len + 1)
    wave = 0.5 + 0.5 * np.cos(t * 2 * np.pi / 6)
    return series(np.concatenate([pre, rally, top * 0.93 + (top / 1.01 - top * 0.93) * wave]))


def test_breakout_through_descending_line_below_the_peak():
    df = triangle()
    m0 = compute("TEST", df.iloc[:-1], W)
    line_tomorrow = m0.P
    assert m0.level_kind == "línea" and line_tomorrow < m0.peak * 0.95
    # Ruptura: cierra un 3% sobre la línea, muy por debajo del máximo de la base.
    c = line_tomorrow * 1.03
    df.iloc[-1] = [c * 0.99, c * 1.005, c * 0.98, c, 2.5e6]
    cl, m = classify(df)
    assert m.cross == 0 and abs(m.P - line_tomorrow) / line_tomorrow < 1e-9
    assert m.C < m.peak * 0.97
    assert cl.state == bo.CONFIRMED, cl


def test_pre_breakout_below_descending_line():
    df = triangle()
    m0 = compute("TEST", df.iloc[:-1], W)
    c = m0.P * 0.975
    df.iloc[-1] = [c, c * 1.004, c * 0.99, c, 1e6]
    cl, m = classify(df)
    # Mañana hay que superar la línea o, si queda por debajo, el máximo de las últimas 3 sesiones.
    assert m.level_kind in ("línea", "rango") and m.cross is None and m.P < m.peak * 0.97
    assert cl.state == bo.PRE and m.P / m.C - 1 < 0.05


def test_flat_top_keeps_peak_as_level():
    m = compute("TEST", flat_base(), W)
    assert m.level_kind == "máximo" and abs(m.P - m.peak) < 1e-6


def test_new_high_without_base_is_not_a_breakout():
    c = np.linspace(50, 120, 260)                       # sube sin pausa
    cl, m = classify(series(c))
    assert m.cross is None and m.blen < 5
    assert cl.state in (bo.BASE, bo.EXTENDED)
