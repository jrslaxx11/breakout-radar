"""Sistema de Martin Luk (campeón del USIC 2025): retrocesos a la EMA 9/21 y el AVWAP en líderes.

Especificación de Jorge (nov-2026), con todos los parámetros en `config/settings.yaml` → `luk`:

Universo: acciones ordinarias de EE. UU. (sin ETF, fondos, SPAC, warrants ni preferentes; ADR extranjeros
excluidos por defecto), capitalización ≥ 300 M, precio ≥ 5, mediana del valor negociado de 20 sesiones
≥ 10 M y ADR(20) ≥ 4%.

Líder: en el escáner de momentum (el 7% de EE. UU. que más sube a 1, 3 o 6 meses desde el mínimo del
periodo), tramo previo ≥ 20% y ≥ 4 ADR, EMA 21 > EMA 50 con ambas al alza, cierre > EMA 50 y a ≤ 25% del
máximo de 52 semanas (salvo EP en las últimas 60 sesiones). La EMA 150 es solo informativa.

Setups (datos diarios; el gatillo es intradía):
- L1 · Retroceso: 2-8 sesiones desde el máximo de 20 (3-7 puntúa más), corrección del máximo al mínimo del
  retroceso de 1 a 3 ADR y ≤ 62% del tramo, EMA 21 al alza, cierre ≥ EMA 21 y zona: el mínimo de hoy o de
  ayer a ≤ 0,2 ADR de la EMA 9, la EMA 21 o el AVWAP, o el cierre a ≤ 1 ADR del soporte más cercano.
- L1b · Perforación: lo mismo, pero el cierre hasta 0,75 ADR bajo la EMA 21 y sobre la EMA 50. Se marca la
  misma noche, con gatillo "reclaim de la EMA 21"; si al día siguiente cierra sobre la EMA 21, pasa a L1.
- L3 · Base: rango de 10 sesiones ≤ 2 ADR y cierre a ≤ 3% del máximo de la base. Solo watchlist.
- EP de hoy: hueco ≥ 10% con volumen ≥ 3 veces la media de 50 sesiones; a vigilar para L1.

Definiciones: EMA(n) con alfa 2/(n+1) sembrada con SMA(n); ADR%(20) = media(High/Low, 20) − 1;
media50_vol = media de las 50 sesiones anteriores, sin la evaluada; EMA ascendente = hoy > hace 3 sesiones;
ruptura = cierre sobre el máximo de las 50 sesiones previas con volumen ≥ 1,5 veces media50_vol;
AVWAP = Σ(TP·V)/ΣV desde el ancla, que es el último EP de ≤ 60 sesiones, si no la última ruptura de
≤ 60 sesiones y si no el mínimo de 20 sesiones.
"""
from __future__ import annotations

import math
import re
from datetime import date

import numpy as np
import pandas as pd

from . import calendar_us

DEFAULTS = {
    # universo
    "include_adrs": False, "min_market_cap": 300e6, "min_price": 5.0, "min_dollar_vol_20d": 10e6,
    "min_adr_pct_20d": 0.04,
    # líder
    "leg_min": 0.20, "leg_adr_min": 4.0, "leg_lookback": 40, "max_dist_52w_high": 0.25, "ema_rise": 3,
    # EP, ruptura y ancla
    "ep_gap": 0.10, "ep_vol_mult": 3.0, "breakout_lookback": 50, "breakout_vol_mult": 1.5, "catalyst_window": 60,
    # L1 / L1b
    "high_window": 20, "pull_min": 2, "pull_max": 8, "pull_best_min": 3, "pull_best_max": 7,
    "depth_adr_min": 1.0, "depth_adr_max": 3.0, "retrace_max": 0.62, "touch_adr": 0.2, "support_adr": 1.0,
    "below21_adr": 0.75,
    # L3
    "l3_range_sessions": 10, "l3_range_adr": 2.0, "l3_near_high": 0.03,
    # ranking
    "w_rs": 0.30, "w_pull": 0.30, "w_theme": 0.20, "w_catalyst": 0.20, "bonus": 0.10, "theme_cap": 4,
    "earnings_window": 5, "earnings_mult": 0.8, "wide_day_pct": 0.03, "wide_day_mult": 0.9,
    # niveles
    "risk_pct": 0.25, "stop_target_pct": 1.5, "stop_max_pct": 3.0, "tick": 0.01,
    # salida
    "top_n": 5, "max_list": 60, "max_l3": 30, "max_ep": 30,
    # régimen
    "health_top": 100, "long_healthy": 0.50, "short_damaged": 0.90, "gap_days": 5,
    # control de calidad
    "backtest_days": 120, "empty_warn_days": 3, "list_target": 15, "coverage_target": 0.70,
}
SETUPS = ("L1", "L1b")
TRIGGER = {"L1": "Rotura del máximo anterior / reclaim VWAP-AVWAP", "L1b": "Reclaim de la EMA 21",
           "L3": "Rotura de {x} solo con stop <= 1,5%"}

FUND_RE = re.compile(r"\bfund\b", re.I)
SPAC_RE = re.compile(r"\bacquisition corp", re.I)
ADR_RE = re.compile(r"depositary|\bADS\b|\bADR\b", re.I)


def cfg_of(c: dict | None) -> dict:
    return {**DEFAULTS, **(c or {})}


# ---------------------------------------------------------------- indicadores
def ema(x: np.ndarray, n: int) -> np.ndarray:
    """EMA con alfa 2/(n+1) sembrada con la SMA de las n primeras velas (NaN antes)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    acc = float(np.mean(x[:n]))
    out[n - 1] = acc
    for i in range(n, len(x)):
        acc = a * x[i] + (1 - a) * acc
        out[i] = acc
    return out


def adr_pct(h: np.ndarray, l: np.ndarray, n: int = 20) -> np.ndarray:
    """ADR%(n) = media(High/Low, n) − 1 (fracción), en cada vela."""
    return pd.Series(np.asarray(h, float) / np.asarray(l, float)).rolling(n).mean().to_numpy() - 1


def mean_prev(v: np.ndarray, n: int) -> np.ndarray:
    """Media de las n velas anteriores a cada una (sin la propia)."""
    v = np.asarray(v, float)
    cv = np.concatenate([[0.0], np.cumsum(v)])
    out = np.full(len(v), np.nan)
    idx = np.arange(n, len(v))
    out[idx] = (cv[idx] - cv[idx - n]) / n
    return out


def days_since_max(h: np.ndarray, s: int, n: int = 20) -> tuple[int, int]:
    """(índice del máximo High de las n últimas sesiones, sesiones desde ese día; 0 = hoy). Con empate, el más reciente."""
    w = np.asarray(h[s - n + 1:s + 1], float)
    p = s - n + 1 + int(np.flatnonzero(w == w.max())[-1])
    return p, s - p


def is_ep(o: np.ndarray, c: np.ndarray, v: np.ndarray, m50: np.ndarray, i: int, cfg: dict) -> bool:
    """EP: Open/Close[-1] − 1 ≥ 10% y Volume ≥ 3 · media50_vol."""
    if i < 1 or not (c[i - 1] > 0) or math.isnan(m50[i]):
        return False
    return bool(o[i] / c[i - 1] - 1 >= cfg["ep_gap"] and v[i] >= cfg["ep_vol_mult"] * m50[i])


def avwap(P: dict, a: int, s: int) -> float:
    """VWAP anclado: Σ(TP·V)/ΣV de la vela a a la s, ambas incluidas."""
    vv = P["cv"][s + 1] - P["cv"][a]
    if vv <= 0:
        return float(P["tp"][s])
    return float((P["cpv"][s + 1] - P["cpv"][a]) / vv)


def avwap_series(h, l, c, v, anchor: int) -> np.ndarray:
    """AVWAP diario desde `anchor` (NaN antes)."""
    tp = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3
    v = np.asarray(v, float)
    out = np.full(len(tp), np.nan)
    pv, vv = np.cumsum(tp[anchor:] * v[anchor:]), np.cumsum(v[anchor:])
    with np.errstate(invalid="ignore", divide="ignore"):
        out[anchor:] = np.where(vv > 0, pv / vv, tp[anchor:])
    return out


def prepare(df: pd.DataFrame, cfg: dict | None = None) -> dict | None:
    """Series y acumulados de un valor para evaluarlo en cualquier sesión sin recalcular."""
    q = cfg_of(cfg)
    if df is None or len(df) < 60:
        return None
    df = df.dropna(subset=["Close", "High", "Low"])
    c = df["Close"].to_numpy(float)
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    o = df["Open"].fillna(df["Close"]).to_numpy(float) if "Open" in df else c.copy()
    v = df["Volume"].fillna(0).to_numpy(float) if "Volume" in df else np.ones(len(c))
    n = len(c)
    if n < 60:
        return None
    m50 = mean_prev(v, 50)
    prev_c = np.r_[np.nan, c[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = o / prev_c - 1
        ep = (gap >= q["ep_gap"]) & (v >= q["ep_vol_mult"] * m50)
        hmax_prev = pd.Series(h).shift(1).rolling(q["breakout_lookback"]).max().to_numpy()
        br = (c > hmax_prev) & (v >= q["breakout_vol_mult"] * m50)
    ar = np.arange(n)
    tp = (h + l + c) / 3
    return {
        "o": o, "h": h, "l": l, "c": c, "v": v, "n": n, "gap": gap,
        "dates": (dates := [pd.Timestamp(x).date().isoformat() for x in df.index]),
        "pos": {d: i for i, d in enumerate(dates)},
        "e9": ema(c, 9), "e21": ema(c, 21), "e50": ema(c, 50), "e150": ema(c, 150),
        "adr": adr_pct(h, l, 20), "m50": m50, "ep": ep, "br": br,
        "last_ep": np.maximum.accumulate(np.where(ep, ar, -1)),
        "last_br": np.maximum.accumulate(np.where(br, ar, -1)),
        "tp": tp, "cpv": np.concatenate([[0.0], np.cumsum(tp * v)]), "cv": np.concatenate([[0.0], np.cumsum(v)]),
        "hi252": pd.Series(h).rolling(252, min_periods=1).max().to_numpy(),
    }


def _up(e: np.ndarray, s: int, k: int) -> bool:
    return bool(s - k >= 0 and not math.isnan(e[s - k]) and e[s] > e[s - k])


def _down(e: np.ndarray, s: int, k: int) -> bool:
    return bool(s - k >= 0 and not math.isnan(e[s - k]) and e[s] < e[s - k])


def health(P: dict, s: int, cfg: dict | None = None) -> str:
    """Sano: cierre sobre la EMA 9 y la EMA 21, ambas al alza. Dañado: cierre bajo las dos, ambas a la baja,
    o hueco bajista ≥ 1 ADR (con su propio ADR) en alguna de las 5 últimas sesiones. Si no, mixto."""
    q = cfg_of(cfg)
    c, e9, e21, k = P["c"], P["e9"], P["e21"], q["ema_rise"]
    if s < 25 or math.isnan(e21[s]):
        return "sin datos"
    # El hueco bajista manda: un valor con las medias sanas pero que abrió ≥ 1 ADR a la baja está dañado.
    gap_down = any(i >= 21 and not math.isnan(P["adr"][i - 1]) and P["gap"][i] <= -P["adr"][i - 1]
                   for i in range(s - q["gap_days"] + 1, s + 1))
    if gap_down or (c[s] < e9[s] and c[s] < e21[s] and _down(e9, s, k) and _down(e21, s, k)):
        return "dañado"
    if c[s] > e9[s] and c[s] > e21[s] and _up(e9, s, k) and _up(e21, s, k):
        return "sano"
    return "mixto"


def context(P: dict, s: int, cfg: dict | None = None) -> dict:
    """Índice o ETF frente a sus EMA 9, 21, 50 y 150 y el orden de las medias."""
    c = P["c"][s]
    vals = {k: P[f"e{k}"][s] for k in (9, 21, 50, 150)}
    order = " > ".join(str(k) for k, _ in sorted(((k, x) for k, x in vals.items() if not math.isnan(x)),
                                                  key=lambda kv: -kv[1]))
    return {"close": float(c), "date": P["dates"][s], "status": health(P, s, cfg), "order": order,
            "aligned": order == "9 > 21 > 50 > 150",
            **{f"vs{k}": (float(c / x - 1) if not math.isnan(x) else None) for k, x in vals.items()},
            **{f"ema{k}": (float(x) if not math.isnan(x) else None) for k, x in vals.items()}}


# ---------------------------------------------------------------- universo
def universe_check(info: dict, industry: str | None, mcap: float | None, price: float | None,
                   mdv: float | None, adr: float | None, cfg: dict | None = None) -> tuple[bool, str, list[str]]:
    """(pasa, motivo si no pasa, flags). Sin capitalización: pasa con el flag "verificar capitalización"."""
    q = cfg_of(cfg)
    name = info.get("name") or ""
    flags = []
    if FUND_RE.search(name):
        return False, "fondo", flags
    if (industry or "") == "Shell Companies" or SPAC_RE.search(name):
        return False, "SPAC", flags
    if info.get("adr") and not q["include_adrs"]:
        return False, "ADR extranjero", flags
    if info.get("adr") is None and info.get("source") not in ("SPX", "MID", "SML", "USA"):
        flags.append("verificar ADR")
    if mcap is None:
        flags.append("verificar capitalización")
    elif mcap < q["min_market_cap"]:
        return False, "capitalización", flags
    if (price or 0) < q["min_price"]:
        return False, "precio", flags
    if (mdv or 0) < q["min_dollar_vol_20d"]:
        return False, "valor negociado", flags
    if (adr or 0) < q["min_adr_pct_20d"]:
        return False, f"ADR(20) < {q['min_adr_pct_20d'] * 100:g}%", flags
    return True, "", flags


# ---------------------------------------------------------------- evaluación diaria
def analyze(P: dict, s: int, cfg: dict | None = None, scan_ok: bool = True) -> dict | None:
    """Líder, setups y métricas de un valor en la sesión de índice `s`. None si no hay datos suficientes."""
    q = cfg_of(cfg)
    if P is None or s < 60 or s >= P["n"]:
        return None
    o, h, l, c, v = P["o"], P["h"], P["l"], P["c"], P["v"]
    e9, e21, e50, e150 = P["e9"], P["e21"], P["e50"], P["e150"]
    adr = P["adr"][s]
    if math.isnan(adr) or adr <= 0 or math.isnan(e50[s]):
        return None
    unit = adr * c[s]
    k = q["ema_rise"]
    out: dict = {"date": P["dates"][s], "close": float(c[s]), "high_today": float(h[s]), "low_today": float(l[s]),
                 "adr": float(adr), "scan": bool(scan_ok)}
    # ---- EP, ruptura y ancla del AVWAP
    W = q["catalyst_window"]
    le, lb = int(P["last_ep"][s]), int(P["last_br"][s])
    ep60 = le >= 0 and s - le < W
    if ep60:
        anc, kind = le, "EP"
    elif lb >= 0 and s - lb < W:
        anc, kind = lb, "ruptura"
    else:
        anc, kind = s - 19 + int(np.argmin(l[s - 19:s + 1])), "mínimo 20"
    av = avwap(P, anc, s)
    out.update({"anchor": kind, "anchor_date": P["dates"][anc], "anchor_since": s - anc, "avwap": av,
                "ep_today": bool(P["ep"][s]), "gap": float(P["gap"][s]) if not math.isnan(P["gap"][s]) else None,
                "vol_x": float(v[s] / P["m50"][s]) if P["m50"][s] > 0 else None})
    # ---- tendencia y líder
    e21up, e50up, e9up = _up(e21, s, k), _up(e50, s, k), _up(e9, s, k)
    trend = bool(e21[s] > e50[s] and e21up and e50up and c[s] > e50[s])
    hi52 = P["hi252"][s]
    dist52 = 1 - c[s] / hi52 if hi52 > 0 else None
    near52 = dist52 is not None and (dist52 <= q["max_dist_52w_high"] or ep60)
    p, days = days_since_max(h, s, q["high_window"])
    high20 = float(h[p])
    a0 = max(0, p - q["leg_lookback"])
    leg_lo = float(np.min(l[a0:p + 1]))
    leg = high20 / leg_lo - 1
    leg_adr = (high20 - leg_lo) / unit
    leg_ok = leg >= q["leg_min"] and leg_adr >= q["leg_adr_min"]
    why = ("no está en el escáner de momentum" if not scan_ok else
           "medias (EMA 21 > EMA 50, ambas al alza y cierre > EMA 50)" if not trend else
           f"a {dist52 * 100:.0f}% del máximo de 52 semanas" if not near52 else
           "tramo previo < 20% o < 4 ADR" if not leg_ok else "")
    leader = not why
    out.update({"leader": leader, "why": why, "trend": trend, "e9up": e9up, "e21up": e21up, "e50up": e50up,
                "ema9": float(e9[s]), "ema21": float(e21[s]), "ema50": float(e50[s]),
                "ema150": float(e150[s]) if not math.isnan(e150[s]) else None,
                "dist52": float(dist52) if dist52 is not None else None, "ep60": ep60,
                "high20": high20, "high_date": P["dates"][p], "days": days, "leg": float(leg),
                "leg_lo": leg_lo, "leg_adr": float(leg_adr)})
    # ---- retroceso
    pull_lo = float(np.min(l[p + 1:s + 1])) if days >= 1 else float(l[s])
    depth_adr = (high20 - pull_lo) / high20 / adr
    retrace = (high20 - pull_lo) / (high20 - leg_lo) if high20 > leg_lo else 1.0
    sups = {"EMA 9": float(e9[s]), "EMA 21": float(e21[s]), "AVWAP": av}
    near_name, near_val = min(sups.items(), key=lambda kv: abs(c[s] - kv[1]))
    dist_adr = abs(c[s] - near_val) / unit
    tol = q["touch_adr"] * unit

    def touched(i: int) -> list[str]:
        t = []
        for name, val in (("EMA 9", e9[i]), ("EMA 21", e21[i]), ("AVWAP", avwap(P, anc, i) if anc <= i else None)):
            if val is not None and not math.isnan(val) and l[i] <= val + tol:
                t.append(name)
        # Tocar solo la EMA 9 cuenta desde la 3.ª sesión de retroceso (en un líder rápido se toca a diario).
        return t if t and (t != ["EMA 9"] or i - p >= 3) else []

    touch = sorted({x for i in (s - 1, s) if i > p for x in touched(i)}, key=["EMA 9", "EMA 21", "AVWAP"].index)
    zone = bool(touch) or dist_adr <= q["support_adr"]
    recovery = bool(c[s] > h[s - 1])
    pidx = [i for i in range(p + 1, s + 1) if not (i == s and recovery)]
    vol_ratio = float(np.mean(v[pidx]) / P["m50"][s]) if pidx and P["m50"][s] > 0 else None
    inside = bool(h[s] <= h[s - 1] and l[s] >= l[s - 1])
    rng = h[s - 6:s + 1] - l[s - 6:s + 1]
    nr7 = bool(rng[-1] <= rng.min())
    out.update({"pull_lo": pull_lo, "depth": float(1 - pull_lo / high20), "depth_adr": float(depth_adr),
                "retrace": float(retrace), "support": near_name, "support_value": float(near_val),
                "dist_adr": float(dist_adr), "touch": touch, "zone": zone, "recovery": recovery,
                "vol_ratio": vol_ratio, "inside": inside, "nr7": nr7,
                "wide_day": float((c[s] - l[s]) / c[s])})
    # ---- setups
    base_ok = (leader and q["pull_min"] <= days <= q["pull_max"]
               and q["depth_adr_min"] <= depth_adr <= q["depth_adr_max"] and retrace <= q["retrace_max"])
    setup, fail = None, ""
    if base_ok and c[s] >= e21[s] and zone:
        setup = "L1"
    elif base_ok and e21[s] - q["below21_adr"] * unit <= c[s] < e21[s] and c[s] > e50[s]:
        setup = "L1b"
    elif leader:
        n10 = q["l3_range_sessions"]
        hi10, lo10 = float(np.max(h[s - n10 + 1:s + 1])), float(np.min(l[s - n10 + 1:s + 1]))
        out.update({"base_hi": hi10, "base_range_adr": (hi10 - lo10) / unit})
        if (hi10 - lo10) / unit <= q["l3_range_adr"] and c[s] >= hi10 * (1 - q["l3_near_high"]):
            setup = "L3"
    if setup is None and leader:
        fail = ("días desde el máximo fuera de 2-8" if not q["pull_min"] <= days <= q["pull_max"] else
                f"corrección de {depth_adr:.1f} ADR (pide 1-3)" if not q["depth_adr_min"] <= depth_adr <= q["depth_adr_max"] else
                f"corrige el {retrace * 100:.0f}% del tramo (máx. 62%)" if retrace > q["retrace_max"] else
                "más de 0,75 ADR bajo la EMA 21 o bajo la EMA 50" if c[s] < e21[s] else "fuera de la zona de soporte")
    out.update({"setup": setup, "setup_why": fail})
    return out


def levels(a: dict, cfg: dict | None = None) -> dict:
    """Entrada, stop y tamaño estimados con datos diarios (el gatillo real es intradía)."""
    q = cfg_of(cfg)
    st = a["setup"]
    if st == "L1":
        entry, level = a.get("high_today", a["close"]) + q["tick"], f"{a['support']} {a['support_value']:.2f}"
    elif st == "L1b":
        entry, level = a["ema21"] + q["tick"], f"EMA 21 {a['ema21']:.2f}"
    else:
        entry, level = a["base_hi"] + q["tick"], f"Máx. base {a['base_hi']:.2f}"
    sp = q["stop_target_pct"] / 100
    return {"entry": entry, "stop": entry * (1 - sp), "stop_min": entry * (1 - q["stop_max_pct"] / 100),
            "stop_pct": q["stop_target_pct"], "size_pct": q["risk_pct"] / q["stop_target_pct"] * 100,
            "r3": entry * (1 + 3 * sp), "r5": entry * (1 + 5 * sp), "level": level,
            "trigger": TRIGGER[st].format(x=f"{entry:.2f}")}


def score(a: dict, rs: float | None, theme_n: int, earn_sessions: int | None, earn_known: bool,
          cfg: dict | None = None) -> dict:
    """Puntuación 0-100: 30% fuerza relativa, 30% retroceso, 20% temática, 20% catalizador; penalizaciones."""
    q = cfg_of(cfg)
    vr = a.get("vol_ratio")
    dry = min(1.0, max(0.0, (1 - vr) / 0.5)) if vr is not None else 0.0
    prox = min(1.0, max(0.0, 1 - a["dist_adr"]))
    bonus = q["bonus"] * ((a["inside"] or a["nr7"]) + a["e9up"] + (q["pull_best_min"] <= a["days"] <= q["pull_best_max"]))
    pull = min(1.0, (dry + prox) / 2 + bonus)
    theme = min(theme_n, q["theme_cap"]) / q["theme_cap"]
    cat = max(0.0, 1 - a["anchor_since"] / q["catalyst_window"]) if a["anchor"] in ("EP", "ruptura") else 0.0
    rs_v = rs if rs is not None else 0.0
    base = 100 * (q["w_rs"] * rs_v + q["w_pull"] * pull + q["w_theme"] * theme + q["w_catalyst"] * cat)
    mult, flags = 1.0, []
    if earn_sessions is not None and 0 <= earn_sessions <= q["earnings_window"]:
        mult *= q["earnings_mult"]
        flags.append("resultados hoy" if earn_sessions == 0 else f"resultados en {earn_sessions} sesiones")
    elif not earn_known:
        flags.append("verificar resultados")
    if a["wide_day"] > q["wide_day_pct"]:
        mult *= q["wide_day_mult"]
        flags.append("requiere gatillo intradía")
    if rs is None:
        flags.append("verificar fuerza relativa")
    return {"score": round(base * mult, 1), "base": round(base, 1), "mult": mult, "flags": flags,
            "parts": {"rs": rs, "pull": pull, "dry": dry, "prox": prox, "bonus": bonus, "theme": theme, "cat": cat}}


def earnings_sessions(next_iso: str | None, today: date) -> int | None:
    if not next_iso:
        return None
    try:
        return calendar_us.sessions_until(today, date.fromisoformat(next_iso))
    except ValueError:
        return None


def mode(counts: dict, cfg: dict | None = None) -> str:
    """Modo sugerido con el termómetro: LARGO si > 50% sanos, CORTO si ≥ 90% dañados, NEUTRO si no."""
    q = cfg_of(cfg)
    n = counts.get("n") or 0
    if not n:
        return "SIN DATOS"
    if counts["good"] / n > q["long_healthy"]:
        return "LARGO"
    if counts["bad"] / n >= q["short_damaged"]:
        return "CORTO"
    return "NEUTRO"


# ---------------------------------------------------------------- control de calidad (histórico)
def history_stats(frames: dict[str, pd.DataFrame], static_ok: dict[str, bool], cfg: dict | None, scan_pct: float,
                  liq: dict, trades: list[dict], prepared: dict | None = None) -> dict:
    """Tamaño de la lista diaria (L1 + L1b) en las últimas sesiones y cobertura de las entradas documentadas.

    `frames`: velas de las acciones líquidas de EE. UU. (las del escáner). `static_ok`: pasa los filtros que
    no cambian con el tiempo (tipo de valor y capitalización). `liq`: {"min_mdv", "min_price"} del escáner."""
    q = cfg_of(cfg)
    syms = list(frames)
    C = pd.DataFrame({s: frames[s]["Close"] for s in syms}).sort_index()
    H = pd.DataFrame({s: frames[s]["High"] for s in syms}).reindex(C.index)
    L = pd.DataFrame({s: frames[s]["Low"] for s in syms}).reindex(C.index)
    V = pd.DataFrame({s: frames[s]["Volume"] for s in syms}).reindex(C.index).fillna(0)
    dv = (C * V).rolling(20).median()
    scan_pop = (C >= liq["min_price"]) & (dv >= liq["min_mdv"])
    scan = pd.DataFrame(False, index=C.index, columns=C.columns)
    for n in (22, 67, 126):
        mom = C / L.rolling(n).min() - 1
        vals = mom.where(scan_pop).to_numpy()
        cut = []
        for row in vals:
            r = np.sort(row[~np.isnan(row)])
            cut.append(r[min(len(r) - 1, int(len(r) * (1 - scan_pct)))] if len(r) else np.inf)
        scan |= mom.ge(pd.Series(cut, index=C.index), axis=0)
    adr = (H / L).rolling(20).mean() - 1
    uni = (C >= q["min_price"]) & (dv >= q["min_dollar_vol_20d"]) & (adr >= q["min_adr_pct_20d"])
    uni &= pd.Series({s: bool(static_ok.get(s)) for s in syms})
    cand = scan & uni
    P = prepared if prepared is not None else {}

    def prep(sym):
        if sym not in P:
            P[sym] = prepare(frames[sym], q)
        return P[sym]

    def eval_at(sym, d):
        pp = prep(sym)
        if pp is None or d not in pp["pos"]:
            return None
        return analyze(pp, pp["pos"][d], q, bool(cand.at[pd.Timestamp(d), sym]) if sym in cand else False)

    dates = [pd.Timestamp(x).date().isoformat() for x in C.index[-q["backtest_days"]:]]
    daily = []
    for d in dates:
        row = cand.loc[pd.Timestamp(d)]
        n1 = n1b = 0
        for sym in row.index[row.to_numpy()]:
            a = eval_at(sym, d)
            if a and a["setup"] == "L1":
                n1 += 1
            elif a and a["setup"] == "L1b":
                n1b += 1
        daily.append({"date": d, "l1": n1, "l1b": n1b})
    tot = [x["l1"] + x["l1b"] for x in daily]
    streak = 0
    for t in reversed(tot):
        if t:
            break
        streak += 1
    cov_rows = []
    for t in trades:
        sym, d = t["sym"], t.get("date")
        row = {**t, "hit": None, "seen": None, "why": ""}
        if not d:
            row["why"] = "sin fecha en la fuente (verificar)"
        elif sym not in frames:
            row["why"] = "no está entre las acciones líquidas de EE. UU. con datos"
        else:
            ix = [x.date().isoformat() for x in C.index]
            if d not in ix:
                row["why"] = "fecha fuera de los datos descargados"
            else:
                i = ix.index(d)
                hit, notes = False, []
                for dd in (ix[i - 1], d):
                    a = eval_at(sym, dd)
                    ts = pd.Timestamp(dd)
                    st = (a or {}).get("setup")
                    if st in SETUPS:
                        hit = True
                        row["seen"] = f"{st} el {dd}"
                        break
                    reason = ("fuera del universo (precio, valor negociado, ADR, tipo o capitalización)" if not uni.at[ts, sym]
                              else "no está en el escáner de momentum" if not scan.at[ts, sym]
                              else (a or {}).get("why") or (a or {}).get("setup_why") or "sin datos")
                    notes.append(f"{dd}: {reason}")
                row["hit"] = hit
                if not hit:
                    row["why"] = "; ".join(notes)
        cov_rows.append(row)
    verified = [r for r in cov_rows if r.get("verified") and r["hit"] is not None]
    return {
        "days": len(daily), "daily": daily,
        "avg": float(np.mean(tot)) if tot else None, "median": float(np.median(tot)) if tot else None,
        "max": int(max(tot)) if tot else None, "over_target": sum(1 for x in tot if x > q["list_target"]),
        "empty_days": sum(1 for x in tot if x == 0), "empty_streak": streak,
        "coverage": {"rows": cov_rows, "n": len(verified), "hit": sum(1 for r in verified if r["hit"]),
                     "pct": (sum(1 for r in verified if r["hit"]) / len(verified)) if verified else None},
        "note": "La capitalización y el tipo de valor son los de hoy; el resto se calcula con los datos de cada día.",
    }


def constants(cfg: dict | None = None) -> dict:
    q = cfg_of(cfg)
    return {**q, "trigger": TRIGGER,
            "sell_plan": ["Vender el 10-15% a +3-5R y subir el stop del resto a la entrada",
                          "El resto, al primer cierre diario bajo la EMA 9 (valores rápidos) o la EMA 21 (tendencias tranquilas); una mecha intradía no cuenta"]}
