"""Métricas técnicas por valor: medias, ATR, rentabilidades, máximos, volumen y base/pivote."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def sma(a: np.ndarray, n: int, end: int) -> float | None:
    """Media simple de `n` valores que terminan en el índice `end` (incluido)."""
    if end + 1 < n or end < 0:
        return None
    return float(np.mean(a[end - n + 1:end + 1]))


def _ret(c: np.ndarray, k: int) -> float | None:
    e = len(c) - 1
    return float(c[e] / c[e - k] - 1) if len(c) > k else None


@dataclass
class Metrics:
    sym: str
    date: str
    n: int
    C: float
    d1: float
    r1m: float | None
    r3m: float | None
    r6m: float | None
    r12m: float | None
    s20: float | None
    s50: float | None
    s150: float | None
    s200: float | None
    s50up: bool | None
    s150up: bool | None
    s200up: bool | None
    atr: float
    atr_pct: float
    hi52: float
    lo52: float
    dhi: float
    vol: float
    v20: float | None          # media 20 sesiones previas (sin hoy)
    v50: float | None          # media 50 sesiones previas (sin hoy)
    rvol: float | None
    vdry: float | None         # volumen medio 10 sesiones (con hoy) / media 50 previas
    mdv: float                 # mediana de valor negociado 20 sesiones (divisa local)
    # base / pivote
    P: float
    piv_date: str
    blen: int
    depth: float
    cross: int | None          # sesiones desde el primer cierre sobre el pivote (0 = hoy)
    any_closed_above: bool
    max_close_since: float | None
    rvol_cross: float | None
    tight: float               # rango de 10 sesiones / cierre
    lo5: float
    lo10: float
    day_pos: float
    gap: float                 # hueco de apertura de hoy
    ep_up: int = 0             # sesiones (últimas 21) con subida ≥ 4% y volumen ≥ 1,8x la media de 50
    ep_down: int = 0           # ídem con caída ≤ -4%
    high: float = 0.0          # máximo y mínimo de la última sesión
    low: float = 0.0
    s10: float | None = None
    s10up: bool | None = None  # SMA10 por encima de su valor de hace 5 sesiones
    s20up: bool | None = None
    adr_pct: float = 0.0       # ADR% al estilo Qullamaggie: media de (máximo/mínimo) en 20 sesiones - 1
    prior_move: float = 0.0    # subida previa: pivote / mínimo de las 63 sesiones anteriores al pivote - 1
    higher_lows: bool | None = None
    extra: dict = field(default_factory=dict)


def compute(sym: str, df: pd.DataFrame, w: dict) -> Metrics | None:
    """Calcula las métricas de un valor. `w` = sección `windows` de settings.yaml."""
    if df is None or len(df) < 130:
        return None
    df = df.dropna(subset=["Close", "High", "Low"])
    c = df["Close"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    o = df["Open"].to_numpy(dtype=float) if "Open" in df else c.copy()
    v = df["Volume"].fillna(0).to_numpy(dtype=float) if "Volume" in df else np.zeros(len(c))
    n = len(c)
    e = n - 1
    if n < 130 or c[e] <= 0:
        return None

    s20, s50, s150, s200 = (sma(c, k, e) for k in (20, 50, 150, 200))
    s50p, s150p, s200p = (sma(c, k, e - 20) for k in (50, 150, 200))

    lo_i = max(1, e - 13)
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(lo_i, e + 1)]
    atr = float(np.mean(tr))

    lb = min(252, n)
    hi52 = float(np.max(h[n - lb:]))
    lo52 = float(np.min(l[n - lb:]))

    v20 = sma(v, 20, e - 1)
    v50 = sma(v, 50, e - 1)
    v10 = sma(v, 10, e)
    dv = sorted(c[i] * v[i] for i in range(max(0, e - 19), e + 1))
    mdv = float(dv[len(dv) // 2])

    # Pivote: máximo de las sesiones [e-lookback, e-min_age] (primera aparición).
    lookback, min_age = w.get("pivot_lookback", 60), w.get("pivot_min_age", 6)
    start = max(0, e - lookback)
    seg = h[start:e - min_age + 1]
    ip = start + int(np.argmax(seg))
    P = float(h[ip])
    Lb = float(np.min(l[ip:e + 1]))
    cw = w.get("cross_window", 5)
    cross_i = next((i for i in range(e - cw, e + 1) if c[i] > P), None)
    max_close_since = float(np.max(c[cross_i:e + 1])) if cross_i is not None else None
    any_above = any(c[i] > P for i in range(e - cw, e + 1))
    rvol_cross = None
    if cross_i is not None:
        base = sma(v, 20, cross_i - 1)
        rvol_cross = float(v[cross_i] / base) if base else None

    hi10, lo10 = float(np.max(h[e - 9:e + 1])), float(np.min(l[e - 9:e + 1]))
    lo5 = float(np.min(l[e - 4:e + 1]))
    rng = h[e] - l[e]
    ep_up = ep_down = 0
    for i in range(max(51, e - 20), e + 1):
        base = sma(v, 50, i - 1)
        if not base or v[i] < 1.8 * base:
            continue
        r = c[i] / c[i - 1] - 1
        if r >= 0.04:
            ep_up += 1
        elif r <= -0.04:
            ep_down += 1
    dates = df.index
    fmt = lambda i: pd.Timestamp(dates[i]).strftime("%Y-%m-%d")  # noqa: E731

    return Metrics(
        sym=sym, date=fmt(e), n=n, C=float(c[e]), d1=float(c[e] / c[e - 1] - 1),
        r1m=_ret(c, w.get("r1m", 21)), r3m=_ret(c, w.get("r3m", 63)),
        r6m=_ret(c, w.get("r6m", 126)), r12m=_ret(c, w.get("r12m", 250)),
        s20=s20, s50=s50, s150=s150, s200=s200,
        s50up=(s50 > s50p) if s50 and s50p else None,
        s150up=(s150 > s150p) if s150 and s150p else None,
        s200up=(s200 > s200p) if s200 and s200p else None,
        atr=atr, atr_pct=atr / c[e], hi52=hi52, lo52=lo52, dhi=float(c[e] / hi52 - 1),
        vol=float(v[e]), v20=v20, v50=v50,
        rvol=float(v[e] / v20) if v20 else None,
        vdry=float(v10 / v50) if v10 is not None and v50 else None,
        mdv=mdv, P=P, piv_date=fmt(ip), blen=e - ip, depth=1 - Lb / P,
        cross=(e - cross_i) if cross_i is not None else None,
        any_closed_above=any_above, max_close_since=max_close_since, rvol_cross=rvol_cross,
        tight=(hi10 - lo10) / c[e], lo5=lo5, lo10=lo10,
        day_pos=float((c[e] - l[e]) / rng) if rng > 0 else 0.5,
        gap=float(o[e] / c[e - 1] - 1) if not math.isnan(o[e]) else 0.0,
        ep_up=ep_up, ep_down=ep_down,
        high=float(h[e]), low=float(l[e]),
        s10=sma(c, 10, e),
        s10up=(sma(c, 10, e) > sma(c, 10, e - 5)) if n > 20 else None,
        s20up=(s20 > sma(c, 20, e - 5)) if s20 and n > 30 else None,
        adr_pct=float(np.mean(h[e - 19:e + 1] / l[e - 19:e + 1]) - 1),
        prior_move=float(P / np.min(l[max(0, ip - 63):ip + 1]) - 1),
        higher_lows=_higher_lows(l, ip, e),
    )


def _higher_lows(l: np.ndarray, ip: int, e: int) -> bool | None:
    """¿Los mínimos de la segunda mitad de la base son más altos que los de la primera?"""
    span = e - ip
    if span < 6:
        return None
    mid = ip + span // 2
    return bool(np.min(l[mid:e + 1]) > np.min(l[ip:mid]))


def rel(r: float | None, b: float | None) -> float | None:
    """Rentabilidad relativa: (1 + r) / (1 + r_índice) - 1."""
    if r is None or b is None:
        return None
    return (1 + r) / (1 + b) - 1


def rs_composite(rs1: float | None, rs3: float | None, rs6: float | None) -> float:
    """Fuerza relativa compuesta: 20% 1 mes, 40% 3 meses, 40% 6 meses."""
    r6 = rs6 if rs6 is not None else (rs3 if rs3 is not None else 0.0)
    return (rs1 or 0.0) * 0.2 + (rs3 or 0.0) * 0.4 + r6 * 0.4


def median(values) -> float | None:
    vals = sorted(x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not vals:
        return None
    return vals[(len(vals) - 1) // 2]
