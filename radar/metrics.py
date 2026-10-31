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
    high: float = 0.0          # máximo y mínimo de la última sesión
    low: float = 0.0
    s10: float | None = None
    s10up: bool | None = None  # SMA10 por encima de su valor de hace 5 sesiones
    s20up: bool | None = None
    adr_pct: float = 0.0       # ADR% al estilo Qullamaggie: media de (máximo/mínimo) en 20 sesiones - 1
    prior_move: float = 0.0    # subida previa: máximo de la base / mínimo de las 63 sesiones anteriores - 1
    higher_lows: bool | None = None
    # Consolidación y nivel de ruptura (ver _base_at)
    peak: float = 0.0          # máximo con el que empieza la consolidación
    level_kind: str = "máximo"  # "máximo" (techo plano), "línea" (resistencia descendente) o "rango" (máximo reciente)
    line_slope: float = 0.0    # pendiente de la resistencia por sesión (≤ 0)
    touch_date: str | None = None  # segundo punto que define la línea
    line: list | None = None   # [[fecha, valor], [fecha, valor]] para dibujarla
    retrace: float | None = None   # parte de la subida previa que ha corregido la base (0-1)
    tight_ratio: float | None = None  # rango diario reciente / rango diario al inicio de la base
    # Momento al estilo Qullamaggie (sus escáneres): cierre / mínimo de 22, 67 y 126 sesiones - 1
    mom1: float | None = None
    mom3: float | None = None
    mom6: float | None = None
    # Foto del setup la víspera de la ruptura (hoy si aún no ha roto): ver _setup y radar/stars.py
    setup: dict = field(default_factory=dict)
    # Mástil y bandera de la consolidación actual (high tight flag): ver radar/htf.py
    pole: dict = field(default_factory=dict)
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

    # Consolidación y nivel de ruptura (Qullamaggie: el precio rompe el borde superior de la
    # consolidación, que puede ser un techo plano o una resistencia descendente: triángulos y flags).
    lookback, base_min = w.get("pivot_lookback", 60), w.get("base_min", 5)
    cw, recent_n = w.get("cross_window", 5), w.get("recent_highs", 3)
    cross_i, base = None, None
    for d in range(max(1, e - cw), e + 1):       # primer día de la ventana que cierra sobre su nivel
        b = _base_at(h, l, c, d, lookback, base_min, recent_n)
        if b is not None and c[d] > b[5]:
            cross_i, base = d, b
            break
    if base is None:                              # sin ruptura: nivel que habría que superar mañana
        base = _base_at(h, l, c, e + 1, lookback, base_min, recent_n, require=False)
    ip, H, slope, jt, line_v, P = base
    d_lvl = cross_i if cross_i is not None else e + 1
    base_end = cross_i - 1 if cross_i is not None else e
    Lb = float(np.min(l[ip:base_end + 1]))
    lo_move = float(np.min(l[max(0, ip - 63):ip + 1]))
    if P > line_v + 1e-9:
        kind = "rango"
    elif H - line_v > 0.02 * H:          # más de un 2% por debajo del máximo: resistencia descendente
        kind = "línea"
    else:
        kind = "máximo"
    max_close_since = float(np.max(c[cross_i:e + 1])) if cross_i is not None else None
    rvol_cross = None
    if cross_i is not None:
        bv = sma(v, 20, cross_i - 1)
        rvol_cross = float(v[cross_i] / bv) if bv else None

    hi10, lo10 = float(np.max(h[e - 9:e + 1])), float(np.min(l[e - 9:e + 1]))
    lo5 = float(np.min(l[e - 4:e + 1]))
    rng = h[e] - l[e]
    dates = df.index
    fmt = lambda i: pd.Timestamp(dates[i]).strftime("%Y-%m-%d")  # noqa: E731
    line_end = fmt(d_lvl) if d_lvl <= e else _next_session(pd.Timestamp(dates[e]))

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
        mdv=mdv, P=float(P), piv_date=fmt(ip), blen=d_lvl - ip if cross_i is not None else e - ip,
        depth=1 - Lb / H,
        cross=(e - cross_i) if cross_i is not None else None,
        any_closed_above=cross_i is not None, max_close_since=max_close_since, rvol_cross=rvol_cross,
        tight=(hi10 - lo10) / c[e], lo5=lo5, lo10=lo10,
        day_pos=float((c[e] - l[e]) / rng) if rng > 0 else 0.5,
        gap=float(o[e] / c[e - 1] - 1) if not math.isnan(o[e]) else 0.0,
        high=float(h[e]), low=float(l[e]),
        s10=sma(c, 10, e),
        s10up=(sma(c, 10, e) > sma(c, 10, e - 5)) if n > 20 else None,
        s20up=(s20 > sma(c, 20, e - 5)) if s20 and n > 30 else None,
        adr_pct=float(np.mean(h[e - 19:e + 1] / l[e - 19:e + 1]) - 1),
        prior_move=float(H / lo_move - 1),
        higher_lows=_higher_lows(l, ip, base_end),
        peak=float(H), level_kind=kind, line_slope=float(slope),
        touch_date=fmt(jt) if jt != ip else None,
        line=[[fmt(ip), float(H)], [line_end, float(line_v)]],
        retrace=float((H - Lb) / (H - lo_move)) if H > lo_move else None,
        tight_ratio=_tight_ratio(h, l, ip, base_end),
        mom1=_mom(c, l, e, 22), mom3=_mom(c, l, e, 67), mom6=_mom(c, l, e, 126),
        setup=_setup(c, h, l, v, base_end, ip, d_lvl - ip if cross_i is not None else e - ip),
        pole=_pole(h, l, ip, base_end, d_lvl - ip if cross_i is not None else e - ip, H, Lb,
                   w.get("pole_days", 40), fmt),
    )


def _pole(h: np.ndarray, l: np.ndarray, ip: int, base_end: int, blen: int, H: float, Lb: float, days: int, fmt) -> dict:
    """Mástil (subida desde el mínimo de las `days` sesiones anteriores al máximo de la base hasta ese
    máximo) y bandera (la consolidación desde el máximo: duración y corrección)."""
    lm = max(0, ip - days)
    lo = lm + int(np.argmin(l[lm:ip + 1]))
    return {
        "pole": float(H / l[lo] - 1), "pole_len": int(ip - lo), "pole_lo": float(l[lo]), "pole_date": fmt(lo),
        "peak": float(H), "peak_date": fmt(ip), "flag_len": int(blen), "depth": float(1 - Lb / H),
        "flag_low": float(Lb), "flag_end": fmt(base_end),
    }


def _mom(c: np.ndarray, l: np.ndarray, s: int, n: int) -> float | None:
    """Subida desde el mínimo de las últimas `n` sesiones (fórmula de los escáneres de Qullamaggie)."""
    if s + 1 < n:
        return None
    return float(c[s] / np.min(l[s - n + 1:s + 1]) - 1)


def _linearity(c: np.ndarray, a: int, b: int) -> float | None:
    """Limpieza de un tramo: movimiento neto / suma de movimientos diarios (1 = línea recta)."""
    if b - a < 3:
        return None
    lr = np.diff(np.log(c[a:b + 1]))
    tot = float(np.sum(np.abs(lr)))
    return float(abs(np.sum(lr)) / tot) if tot > 0 else None


def _setup(c: np.ndarray, h: np.ndarray, l: np.ndarray, v: np.ndarray, s: int, ip: int, blen: int) -> dict:
    """Rasgos del setup el día `s` (último día de la base) para la puntuación en estrellas.

    Las distancias y rangos van en unidades de ADR del propio valor, que es como Qullamaggie juzga lo
    que está "cerca" o "estrecho" en valores de volatilidad muy distinta.
    """
    if s < 50:
        return {}
    adr = float(np.mean(h[s - 19:s + 1] / l[s - 19:s + 1]) - 1)
    if adr <= 0:
        return {}
    unit = adr * c[s]
    s10, s20, s50 = sma(c, 10, s), sma(c, 20, s), sma(c, 50, s)
    s20p = sma(c, 20, s - 5)
    lo = max(0, s - 125)
    lo6 = lo + int(np.argmin(l[lo:s + 1]))
    lm = max(0, ip - 63)
    lo_i = lm + int(np.argmin(l[lm:ip + 1]))
    v50 = float(np.mean(v[s - 50:s])) if s >= 50 else 0.0
    return {
        "adr": adr,
        "mom3": _mom(c, l, s, 67),
        "d10": float((c[s] - s10) / unit),                         # distancia a la SMA10 en ADR
        "d20": float((c[s] - s20) / unit),
        "sp": float((s20 - s50) / unit),                           # SMA20 sobre la SMA50 en ADR
        "s20up": bool(s20p is not None and s20 > s20p),
        "lo10": float((np.min(l[s - 2:s + 1]) - s10) / unit),     # mínimos de 3 sesiones frente a la SMA10
        "t3": float((np.max(h[s - 2:s + 1]) - np.min(l[s - 2:s + 1])) / unit),
        "t5": float((np.max(h[s - 4:s + 1]) - np.min(l[s - 4:s + 1])) / unit),
        "rng": float((h[s] - l[s]) / unit),
        "vd5": float(np.mean(v[s - 4:s + 1]) / v50) if v50 > 0 else None,
        "lin": _linearity(c, lo_i, ip),
        "bases": _count_bases(h, c, lo6, s),
        "blen": int(blen),
    }


def _count_bases(h: np.ndarray, c: np.ndarray, a: int, s: int) -> int:
    """Bases completadas entre `a` y `s`: pausas de ≥ 5 sesiones sin superar el máximo alcanzado,
    seguidas de un cierre por encima de él."""
    run_hi, pause, cnt = h[a], 0, 0
    for i in range(a + 1, s + 1):
        if c[i] > run_hi:
            if pause >= 5:
                cnt += 1
            run_hi, pause = max(run_hi, h[i]), 0
        else:
            pause += 1
    return cnt


def _early_low(l: np.ndarray, ip: int, end: int) -> bool:
    """¿La base tocó su zona de mínimos (a ≤ 1% del mínimo) en sus dos primeros tercios?

    Es la condición de Qullamaggie de mínimos crecientes vista desde el soporte: en un triángulo o
    flag el precio no vuelve a perforar el suelo al final; en un rebound en V el mínimo es reciente.
    """
    span = end - ip
    support = float(np.min(l[ip:end + 1]))
    i_low = ip + int(np.argmax(l[ip:end + 1] <= support * 1.01))
    return 3 * (i_low - ip) <= 2 * span


def _base_at(h: np.ndarray, l: np.ndarray, c: np.ndarray, d: int, lookback: int, base_min: int, recent_n: int,
             require: bool = True):
    """Consolidación vista el día `d` con las sesiones anteriores (d-1 incluida).

    - Máximo de la base (H): el más alto entre `lookback` y `base_min` sesiones atrás (primera aparición).
      Si algún cierre posterior lo superó, esa base ya se rompió: no vale (None, o con `require=False`
      el máximo más reciente como "base en formación").
    - Resistencia: la línea más plana que parte de H y deja por debajo todos los máximos posteriores
      (tangente superior): plana en un canal, descendente en triángulos y flags. Solo se usa si la base
      tocó su zona de mínimos en sus dos primeros tercios (mínimos crecientes); si el mínimo es reciente
      (rebote en V), la resistencia es H.
    - Nivel de ruptura = el mayor entre la línea proyectada al día `d` y el máximo de las `recent_n`
      sesiones anteriores (incluye los máximos intradía que superaron H sin cerrar por encima).
    Devuelve (índice del máximo, H, pendiente, índice del 2.º punto, línea en d, nivel) o None.
    """
    start = max(0, d - lookback)
    end_pk = d - base_min
    ip = start + int(np.argmax(h[start:end_pk + 1])) if end_pk >= start else None
    if ip is None or (d - 1 > ip and float(np.max(c[ip + 1:d])) > h[ip]):
        if require:
            return None
        ip = start + int(np.argmax(h[start:d]))
        H = float(h[ip])
        return ip, H, 0.0, ip, H, H
    H = float(h[ip])
    slope, jt = 0.0, ip
    if d - 1 > ip and _early_low(l, ip, d - 1):
        js = np.arange(ip + 1, d)
        slopes = (h[ip + 1:d] - H) / (js - ip)
        k = int(np.argmax(slopes))
        if slopes[k] < 0:
            slope, jt = float(slopes[k]), int(js[k])
    line_v = H + slope * (d - ip)
    lo = max(ip + 1, d - recent_n)
    recent = float(np.max(h[lo:d])) if lo < d else line_v
    return ip, H, slope, jt, line_v, max(line_v, recent)


def _tight_ratio(h: np.ndarray, l: np.ndarray, ip: int, end: int) -> float | None:
    """Estrechamiento: rango de precios de las últimas sesiones de la base / rango de toda la base."""
    nb = end - ip
    if nb < 4:
        return None
    k = min(5, nb // 2)
    full = float(np.max(h[ip:end + 1]) - np.min(l[ip:end + 1]))
    if full <= 0:
        return None
    return float((np.max(h[end - k + 1:end + 1]) - np.min(l[end - k + 1:end + 1])) / full)


def _next_session(ts: pd.Timestamp) -> str:
    nxt = ts + pd.Timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += pd.Timedelta(days=1)
    return nxt.strftime("%Y-%m-%d")


def _higher_lows(l: np.ndarray, ip: int, e: int) -> bool | None:
    """Mínimos crecientes: el último tercio de la base se mantiene por encima del mínimo de la base."""
    span = e - ip
    if span < 6:
        return None
    support = float(np.min(l[ip:e + 1]))
    k3 = max(1, span // 3)
    return bool(float(np.min(l[e - k3 + 1:e + 1])) > support)


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
