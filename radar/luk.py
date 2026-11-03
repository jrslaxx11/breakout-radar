"""Retrocesos al estilo Martin Luk (campeón del USIC 2025): su entrada principal en largos.

Según el estudio de 112 directos de 2026 (James Muninn, nov-2026), el 65,9% de sus entradas largas son
retrocesos y solo el 2,3% rupturas de base: "espera a que la acción demuestre su fuerza, la deja retroceder
3-7 días hasta la EMA 9 y la EMA 21 al alza y el AVWAP, y entra en un marco intradía" (recuperar el VWAP o
el AVWAP, romper una cuña o el rango de apertura de 1-5 minutos, o perforar la apertura y recuperarla).
Con datos diarios se detecta la mitad diaria del setup; el gatillo es intradía y se deja al operador.

- Líder: en el escáner de momentum (el 7% de EE. UU. que más sube a 1, 3 o 6 meses), ADR ≥ 3% y un tramo
  previo de al menos un 20% y 4 ADR desde el mínimo de las 40 sesiones anteriores al máximo.
- Tendencia: EMA 21 sobre la EMA 50 y ambas al alza; cierre sobre la EMA 50.
- Retroceso: el máximo de las 10 últimas sesiones quedó hace 2-8 sesiones, corrección ≤ 3,5 ADR y ≤ 62%
  del tramo (MRVL corrigió el 55% de su tramo antes de la entrada del 31-mar-2026).
- Zona: el mínimo de hoy o de ayer toca la EMA 9 (desde la 3.ª sesión de retroceso), la EMA 21 o el AVWAP
  anclado en el mínimo del tramo (con 0,2 ADR de margen) y el cierre no se aleja más de 0,75 ADR por debajo
  de la EMA 21: sus "sacudidas" (perforar y recuperar) también cuentan.
- Estados: "recupera" (tocó la zona en las 3 últimas sesiones y hoy cierra sobre el máximo de ayer y la
  EMA 9: el día típico de su entrada), "en zona" y "acercándose" (aún a ≤ 1 ADR sobre la EMA 9).

Plan con sus números: riesgo 0,3-0,5% de la cuenta con stop en el mínimo intradía (mediana 1,3%), posición
hasta el 35%, venta del 10-15% a +3-5R y el resto al primer cierre bajo la EMA 9 (valores rápidos) o la
EMA 21 (tendencias tranquilas).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULTS = {
    "adr_min": 0.03, "leg_min": 0.20, "leg_adr_min": 4.0, "leg_lookback": 40, "peak_window": 10,
    "pull_min": 2, "pull_max": 8, "depth_adr_max": 3.5, "retrace_max": 0.62, "touch_adr": 0.2,
    "below21_adr": 0.75, "near_adr": 1.0, "fast_adr": 0.05, "health_top": 100,
}
STATES = ("recupera", "en zona", "acercándose")


def ema(x: np.ndarray, n: int) -> np.ndarray:
    """EMA estándar (la de TradingView y la de pandas con adjust=False), sembrada con el primer valor."""
    a = 2.0 / (n + 1)
    out = np.empty(len(x), dtype=float)
    acc = float(x[0])
    for i, v in enumerate(x):
        acc = a * float(v) + (1 - a) * acc if i else acc
        out[i] = acc
    return out


def avwap(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray, anchor: int) -> np.ndarray:
    """VWAP anclado con datos diarios (precio típico × volumen) desde la vela `anchor`; NaN antes."""
    tp = (h + l + c) / 3.0
    out = np.full(len(c), np.nan)
    pv = np.cumsum(tp[anchor:] * v[anchor:])
    vv = np.cumsum(v[anchor:])
    with np.errstate(invalid="ignore", divide="ignore"):
        out[anchor:] = np.where(vv > 0, pv / vv, tp[anchor:])
    return out


def evaluate(df: pd.DataFrame, cfg: dict | None = None) -> dict | None:
    """Retroceso de Luk en la última sesión de `df` (velas diarias) o None si no lo hay."""
    q = {**DEFAULTS, **(cfg or {})}
    if df is None or len(df) < 80:
        return None
    df = df.dropna(subset=["Close", "High", "Low"])
    c = df["Close"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    v = df["Volume"].fillna(0).to_numpy(dtype=float) if "Volume" in df else np.ones(len(c))
    n = len(c)
    s = n - 1
    if n < 80 or c[s] <= 0:
        return None
    adr = float(np.mean(h[s - 19:s + 1] / l[s - 19:s + 1]) - 1)
    if adr < q["adr_min"]:
        return None
    unit = adr * c[s]
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    # Tendencia: EMA 21 > EMA 50, ambas al alza, y el cierre sobre la EMA 50.
    if not (e21[s] > e50[s] and e21[s] > e21[s - 5] and e50[s] > e50[s - 10] and c[s] > e50[s]):
        return None
    # Máximo reciente y días de retroceso.
    w = q["peak_window"]
    p = s - w + 1 + int(np.argmax(h[s - w + 1:s + 1]))
    days = s - p
    if not q["pull_min"] <= days <= q["pull_max"]:
        return None
    a0 = max(0, p - q["leg_lookback"])
    anchor = a0 + int(np.argmin(l[a0:p + 1]))
    leg_lo, peak = float(l[anchor]), float(h[p])
    leg = peak / leg_lo - 1
    if leg < q["leg_min"] or (peak - leg_lo) / unit < q["leg_adr_min"]:
        return None
    pull_lo = float(np.min(l[p + 1:s + 1]))
    depth_adr = (peak - pull_lo) / unit
    retrace = (peak - pull_lo) / (peak - leg_lo)
    if depth_adr > q["depth_adr_max"] or retrace > q["retrace_max"]:
        return None
    if c[s] < e21[s] - q["below21_adr"] * unit:
        return None
    av = avwap(h, l, c, v, anchor)
    tol = q["touch_adr"] * unit

    def touched(i: int) -> list[str]:
        out = []
        if l[i] <= e9[i] + tol:
            out.append("EMA 9")
        if l[i] <= e21[i] + tol:
            out.append("EMA 21")
        if not np.isnan(av[i]) and l[i] <= av[i] + tol and c[i] >= av[i] - q["below21_adr"] * unit:
            out.append("AVWAP")
        return out

    # Tocar solo la EMA 9 cuenta a partir de 3 sesiones de retroceso (en un líder rápido, la EMA 9 se toca
    # casi a diario); la EMA 21 o el AVWAP, desde 2 (MRVL, 30-mar-2026).
    def zone(i: int) -> list[str]:
        t = touched(i)
        return t if t and (t != ["EMA 9"] or i - p >= 3) else []

    recent = {i: zone(i) for i in range(max(p + 1, s - 2), s + 1)}
    zone_now = zone(s) or (zone(s - 1) if s - 1 > p else [])
    if c[s] > h[s - 1] and c[s] > e9[s] and any(recent.values()):
        state = "recupera"
        levels = sorted({x for t in recent.values() for x in t}, key=["EMA 9", "EMA 21", "AVWAP"].index)
    elif zone_now:
        state, levels = "en zona", zone_now
    elif (l[s] - e9[s]) / unit <= q["near_adr"]:
        state, levels = "acercándose", []
    else:
        return None
    undercut = bool(np.min(l[max(p + 1, s - 2):s + 1]) < e21[s] and c[s] >= e21[s] - q["below21_adr"] * unit)
    v50 = float(np.mean(v[max(0, s - 50):s])) or 1.0
    vdry = float(np.mean(v[p + 1:s + 1])) / v50
    conv = abs(e9[s] - e21[s]) / unit
    trail = "EMA 9" if adr >= q["fast_adr"] else "EMA 21"
    checks = [
        {"key": "pull", "ok": 3 <= days <= 7, "label": "Retroceso de 3-7 sesiones (su rango habitual)", "value": f"{days} sesiones"},
        {"key": "stack", "ok": bool(e9[s] > e21[s] > e50[s]), "label": "EMA 9 > EMA 21 > EMA 50",
         "value": "sí" if e9[s] > e21[s] > e50[s] else "la EMA 9 ya cruzó la 21"},
        {"key": "vol", "ok": vdry <= 0.85, "label": "Retroceso con volumen bajo (≤ 85% de la media de 50 sesiones)",
         "value": f"{vdry * 100:.0f}% de la media"},
        {"key": "conf", "ok": len(levels) >= 2 or (not np.isnan(av[s]) and abs(av[s] - e21[s]) <= 0.5 * unit),
         "label": "Confluencia de soportes (EMA 9/21 y AVWAP juntos)",
         "value": ", ".join(levels) if levels else f"AVWAP a {_es(abs(av[s] - e21[s]) / unit)} ADR de la EMA 21"},
        {"key": "depth", "ok": depth_adr <= 2.5, "label": "Corrección moderada (≤ 2,5 ADR)", "value": f"{_es(depth_adr)} ADR, {retrace * 100:.0f}% del tramo"},
    ]
    return {
        "state": state, "levels": levels, "undercut": undercut, "days": days,
        "peak": peak, "peak_date": _d(df, p), "leg_lo": leg_lo, "anchor_date": _d(df, anchor), "leg": leg,
        "pull_lo": pull_lo, "depth": 1 - pull_lo / peak, "depth_adr": depth_adr, "retrace": retrace,
        "ema9": float(e9[s]), "ema21": float(e21[s]), "ema50": float(e50[s]), "avwap": float(av[s]),
        "d9": (c[s] - e9[s]) / unit, "d21": (c[s] - e21[s]) / unit, "conv": conv, "vdry": vdry,
        "adr": adr, "trail": trail, "trail_value": float(e9[s] if trail == "EMA 9" else e21[s]),
        "checks": checks, "points": sum(1 for k in checks if k["ok"]),
    }


def _es(x: float, d: int = 1) -> str:
    """Número con coma decimal."""
    return f"{x:.{d}f}".replace(".", ",")


def _d(df: pd.DataFrame, i: int) -> str:
    return pd.Timestamp(df.index[i]).date().isoformat()


def health(frames: dict[str, pd.DataFrame]) -> dict:
    """Su termómetro: "cuando 90 de los 100 valores de mi lista tienen mala pinta, paso a cortos". Sanos:
    cierre sobre la EMA 21 al alza. Rotos: cierre bajo la EMA 9 y la EMA 21, ambas a la baja. La pendiente se
    mide a 5 sesiones: a 1 sesión es redundante (un cierre sobre la EMA siempre la hace subir ese día)."""
    good, bad = [], []
    n = 0
    for sym, df in frames.items():
        c = df["Close"].dropna().to_numpy(dtype=float)
        if len(c) < 60:
            continue
        n += 1
        e9, e21 = ema(c, 9), ema(c, 21)
        s = len(c) - 1
        if c[s] > e21[s] and e21[s] > e21[s - 5]:
            good.append(sym)
        elif c[s] < e9[s] and c[s] < e21[s] and e9[s] < e9[s - 5] and e21[s] < e21[s - 5]:
            bad.append(sym)
    return {"n": n, "good": len(good), "bad": len(bad), "mixed": n - len(good) - len(bad), "bad_syms": bad[:40]}


def constants() -> dict:
    return {
        **DEFAULTS,
        "risk_rule": "Riesgo 0,3-0,5% de la cuenta por operación (0,15-0,25% en rachas malas)",
        "stop_rule": "Stop en el mínimo intradía de la vela de entrada (1, 5 o 15 minutos): mediana 1,3%, rara vez más del 2-3%",
        "entry_rule": "Gatillo intradía en la zona: recuperar el VWAP o el AVWAP, romper una cuña o el rango de apertura de 1-5 minutos, o perforar la apertura y recuperarla",
        "sell_plan": ["Vender el 10-15% a +3-5R y subir el stop del resto a la entrada",
                      "El resto, al primer cierre diario bajo la EMA 9 (valores rápidos) o la EMA 21 (tendencias tranquilas); una mecha intradía no cuenta"],
        "max_position": 0.35,
    }
