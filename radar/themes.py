"""Fases 2-3: asignación de temáticas, estadísticas internas y puntuación 0-100."""
from __future__ import annotations


from .metrics import median, sma


def clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))


def build_lookup(theme_defs: dict) -> tuple[dict, dict, dict]:
    by_ticker, by_gics, by_yahoo = {}, {}, {}
    for key, t in theme_defs.items():
        for s in t.get("tickers", []) or []:
            by_ticker[str(s)] = key
        for g in t.get("gics", []) or []:
            by_gics[g] = key
        for y in t.get("yahoo", []) or []:
            by_yahoo[y] = key
    return by_ticker, by_gics, by_yahoo


def assign(sym: str, info: dict, profile: dict | None, lookup: tuple[dict, dict, dict]) -> str | None:
    """Prioridad: lista fija > subindustria GICS > pista manual > industria de Yahoo."""
    by_ticker, by_gics, by_yahoo = lookup
    if sym in by_ticker:
        return by_ticker[sym]
    if info.get("gics_sub") and info["gics_sub"] in by_gics:
        return by_gics[info["gics_sub"]]
    if info.get("gics_sub"):
        return None
    if info.get("hint"):
        # La pista sirve de reserva; si Yahoo da una industria concreta, manda la industria.
        ind = (profile or {}).get("industry")
        return by_yahoo.get(ind, info["hint"]) if ind else info["hint"]
    ind = (profile or {}).get("industry")
    return by_yahoo.get(ind) if ind else None


def etf_stats(prices: dict, sym: str, bench: dict, w: dict) -> dict | None:
    from .metrics import compute, rel

    df = prices.get(sym)
    m = compute(sym, df, w) if df is not None else None
    if m is None:
        return None
    v = df["Volume"].fillna(0).to_numpy(dtype=float)
    e = len(v) - 1
    v20, v50 = sma(v, 20, e), sma(v, 50, e)
    return {
        "sym": sym, "r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m,
        "rs1": rel(m.r1m, bench.get("r1m")), "rs3": rel(m.r3m, bench.get("r3m")),
        "rs6": rel(m.r6m, bench.get("r6m")), "vtr": (v20 / v50) if v20 and v50 else None,
        "vs50": m.C / m.s50 - 1 if m.s50 else None, "dhi": m.dhi,
    }


def stats(members: list[dict], etfs: list[dict]) -> dict:
    """Estadísticas de la cesta. La amplitud usa solo valores de selección no sesgada."""
    unb = [a for a in members if a["unbiased"]]
    br = unb if len(unb) >= 6 else members
    n = len(br) or 1
    vdry = median(a["m"].vdry for a in br)
    ev = [e["vtr"] for e in etfs if e and e.get("vtr")]
    vol = ((vdry or 1) + sum(ev) / len(ev)) / 2 if ev else (vdry or 1)
    return {
        "n": len(members), "n_unbiased": len(unb), "biased": len(unb) < 6,
        "rs1": median(a["rs1"] for a in members), "rs3": median(a["rs3"] for a in members),
        "rs6": median(a["rs6"] for a in members), "rsc": median(a["rsc"] for a in members),
        "p50": sum(1 for a in br if a["m"].s50 and a["m"].C > a["m"].s50) / n,
        "p200": sum(1 for a in br if a["m"].s200 and a["m"].C > a["m"].s200) / n,
        "near_hi": sum(1 for a in br if a["m"].dhi >= -0.10) / n,
        "dhi_med": median(a["m"].dhi for a in br),
        "vol": vol, "leaders": sum(1 for a in members if (a.get("rs_pct") or 0) >= 0.8),
        "n_breadth": len(br),
    }


DEFAULT_WEIGHTS = {"rs": 45, "consistency": 15, "breadth": 20, "highs": 10, "volume": 10}


def rs_ranks(theme_stats: dict[str, dict]) -> dict[str, float]:
    """Posición de cada temática por fuerza relativa compuesta: 1 = la más fuerte, 0 = la más débil."""
    keys = sorted(theme_stats, key=lambda k: theme_stats[k]["rsc"] or 0)
    n = len(keys)
    return {k: (i / (n - 1) if n > 1 else 1.0) for i, k in enumerate(keys)}


def score(st: dict, rs_rank: float, weights: dict | None = None) -> dict:
    """Puntuación 0-100 de una temática.

    - Fuerza relativa: posición frente a las demás temáticas (comparación entre grupos).
    - Consistencia: plazos (1, 3 y 6 meses) en los que la mediana supera a su índice (absoluto).
    - Amplitud: % de valores sobre su SMA50 y su SMA200.
    - Cerca de máximos: % de valores a menos de un 10% del máximo de 52 semanas (60% o más = máximo).
    - Volumen: volumen reciente frente al habitual (0,8x = 0; 1,2x o más = máximo).
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    pos = sum(1 for x in (st["rs1"], st["rs3"], st["rs6"]) if x is not None and x > 0)
    parts = {
        "rs": w["rs"] * clamp(rs_rank, 0, 1),
        "consistency": w["consistency"] * pos / 3,
        "breadth": w["breadth"] / 2 * (st["p50"] + st["p200"]),
        "highs": w["highs"] * clamp(st["near_hi"] / 0.6, 0, 1),
        "volume": w["volume"] * clamp((st["vol"] - 0.8) / 0.4, 0, 1),
    }
    parts["total"] = round(sum(parts.values()), 2)
    return parts


def status(st: dict) -> str:
    rs1, rs3, rs6 = st["rs1"] or 0, st["rs3"] or 0, st["rs6"] or 0
    if rs3 > 0 and rs6 > 0 and st["p50"] >= 0.6:
        # Liderazgo real exige estar cerca de máximos; si no, es un rebote desde mínimos.
        if st["near_hi"] >= 0.30 or (st.get("dhi_med") or -1) >= -0.15:
            return "Lidera"
        return "Mejora (rebote lejos de máximos)"
    if rs1 > 0 and rs3 > 0:
        return "Mejora"
    if rs1 > 0:
        return "Empieza a mejorar"
    if rs6 > 0:
        return "Pierde fuerza"
    return "Rezagada"
