"""Fase 1: régimen de mercado (índices, amplitud, volatilidad) y su clasificación."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import compute, sma


def index_rows(prices: dict[str, pd.DataFrame], indices: list[dict], w: dict) -> list[dict]:
    rows = []
    for ix in indices:
        df = prices.get(ix["sym"])
        m = compute(ix["sym"], df, w) if df is not None else None
        if m is None:
            rows.append({**ix, "available": False})
            continue
        rows.append({
            **ix, "available": True, "date": m.date, "close": m.C, "d1": m.d1,
            "vs20": m.C / m.s20 - 1 if m.s20 else None,
            "vs50": m.C / m.s50 - 1 if m.s50 else None,
            "vs200": m.C / m.s200 - 1 if m.s200 else None,
            "s50up": m.s50up, "r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m, "dhi": m.dhi,
        })
    return rows


def breadth(prices: dict[str, pd.DataFrame], symbols: list[str], offset: int = 0) -> dict | None:
    """% sobre SMA20/50/200 y nuevos máximos/mínimos de 52 semanas, `offset` sesiones atrás."""
    n = a20 = a50 = a200 = nh = nl = 0
    for s in symbols:
        df = prices.get(s)
        if df is None or len(df) < 230:
            continue
        c = df["Close"].to_numpy(dtype=float)
        h = df["High"].to_numpy(dtype=float)
        l = df["Low"].to_numpy(dtype=float)
        e = len(c) - 1 - offset
        if e < 210:
            continue
        n += 1
        if c[e] > sma(c, 20, e):
            a20 += 1
        if c[e] > sma(c, 50, e):
            a50 += 1
        if c[e] > sma(c, 200, e):
            a200 += 1
        lo = max(0, e - 251)
        if h[e] >= np.max(h[lo:e]):
            nh += 1
        if l[e] <= np.min(l[lo:e]):
            nl += 1
    if not n:
        return None
    return {"n": n, "p20": a20 / n, "p50": a50 / n, "p200": a200 / n, "nh": nh, "nl": nl}


def classify_regime(idx: list[dict], br: dict, vix: dict) -> dict:
    """Regla explícita: suma de señales. ≥ 5 favorable, 2-4 mixto, ≤ 1 desfavorable."""
    by = {r["sym"]: r for r in idx if r.get("available")}
    rules = []

    def add(ok: bool | None, txt: str):
        if ok is None:
            return
        rules.append({"signal": txt, "points": 1 if ok else -1})

    spx = by.get("^GSPC")
    if spx:
        rules.append({"signal": "S&P 500 sobre SMA50", "points": 1 if (spx["vs50"] or 0) > 0 else -1})
        rules.append({"signal": "S&P 500 sobre SMA200", "points": 1 if (spx["vs200"] or 0) > 0 else -1})
    if by.get("^NDX"):
        add((by["^NDX"]["vs50"] or 0) > 0, "Nasdaq 100 sobre SMA50")
    if by.get("^RUT"):
        add((by["^RUT"]["vs50"] or 0) > 0, "Russell 2000 sobre SMA50")
    sp = (br or {}).get("SPX", {}).get("now")
    if sp:
        if sp["p50"] >= 0.60:
            rules.append({"signal": "Amplitud S&P 500 ≥ 60% sobre SMA50", "points": 1})
        elif sp["p50"] <= 0.40:
            rules.append({"signal": "Amplitud S&P 500 ≤ 40% sobre SMA50", "points": -1})
    hl = (br or {}).get("nhnl") or []
    if hl:
        net = sum(x["nh"] - x["nl"] for x in hl[:5])
        add(net > 0, "Nuevos máximos > mínimos (5 sesiones, S&P 1500)")
    if vix.get("vix") and vix.get("vix3m"):
        add(vix["vix"] < vix["vix3m"], "VIX en contango (VIX < VIX 3 meses)")
    eu = by.get("^STOXX")
    if eu:
        add((eu["vs50"] or 0) > 0, "STOXX 600 sobre SMA50")
    asia = [by[s] for s in ("^N225", "^TWII", "^KS11", "^HSI", "^AXJO") if s in by]
    if asia:
        up = sum(1 for r in asia if (r["vs50"] or 0) > 0)
        add(up > len(asia) / 2, "Mayoría de índices asiáticos sobre SMA50")
    total = sum(r["points"] for r in rules)
    label = "FAVORABLE" if total >= 5 else "DESFAVORABLE" if total <= 1 else "MIXTO"
    return {"label": label, "score": total, "rules": rules}


def regime(prices: dict, settings: dict, sp_groups: dict[str, list[str]]) -> dict:
    w = settings["windows"]
    idx = index_rows(prices, settings["regime"]["indices"], w)
    br: dict = {}
    for k, syms in sp_groups.items():
        br[k] = {f"now" if o == 0 else f"t{o}": breadth(prices, syms, o) for o in (0, 5, 10, 21)}
    all_syms = [s for syms in sp_groups.values() for s in syms]
    nhnl = []
    for o in range(10):
        b = breadth(prices, all_syms, o)
        if b:
            ref = prices.get("^GSPC")
            d = ref.index[-1 - o].strftime("%Y-%m-%d") if ref is not None and len(ref) > o else str(o)
            nhnl.append({"date": d, "nh": b["nh"], "nl": b["nl"]})
    br["nhnl"] = nhnl
    vix = {}
    for s, k in (("^VIX", "vix"), ("^VIX3M", "vix3m")):
        df = prices.get(s)
        if df is not None and len(df):
            vix[k] = float(df["Close"].iloc[-1])
    out = classify_regime(idx, br, vix)
    return {**out, "indices": idx, "breadth": br, "vix": vix}
