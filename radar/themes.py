"""Fases 2-3: asignación de temáticas, estadísticas internas y puntuación 0-100."""
from __future__ import annotations

from datetime import date

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


def theme_catalyst(key: str, overrides: dict, today: date) -> dict | None:
    """Catalizador manual vigente (no caducado) o None si no hay dato disponible."""
    c = (overrides.get("theme_catalysts") or {}).get(key)
    if not c:
        return None
    try:
        d = c["date"] if isinstance(c["date"], date) else date.fromisoformat(str(c["date"]))
    except (KeyError, ValueError):
        return None
    if (today - d).days > overrides.get("expires_days", 21):
        return None
    return {"points": float(c.get("points", 0)), "note": c.get("note", ""), "source": c.get("source", ""),
            "date": d.isoformat()}


def catalyst_auto(st: dict) -> dict | None:
    """Huella de catalizadores en precio y volumen, disponible para todas las temáticas.

    Proporción neta de valores con al menos una sesión de +4% y volumen ≥ 1,8x en las últimas
    21 sesiones (resultados, contratos, guías…) menos los que tuvieron una caída equivalente.
    """
    n = st.get("n_breadth") or 0
    if n < 5:
        return None
    net = (st["events_up"] - st["events_down"]) / n
    pts = 15 * clamp(0.5 + 2.5 * net, 0, 1)
    note = (f"Huella automática (21 sesiones): {st['events_up']} de {n} con subida ≥ 4% y volumen ≥ 1,8x, "
            f"{st['events_down']} con caída equivalente")
    return {"points": round(pts, 2), "note": note, "source": "", "date": None, "auto": True}


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
        "events_up": sum(1 for a in br if a["m"].ep_up > 0),
        "events_down": sum(1 for a in br if a["m"].ep_down > 0),
        "n_breadth": len(br),
    }


def score(st: dict, catalyst: dict | None) -> dict:
    """RS 30 · consistencia 20 · amplitud 20 · volumen 15 · catalizadores 15."""
    p_rs = 30 * clamp(0.5 + (st["rsc"] or 0) / 0.6, 0, 1)
    p_con = (20 / 3) * sum(1 for x in (st["rs1"], st["rs3"], st["rs6"]) if x is not None and x > 0)
    p_br = 10 * st["p50"] + 10 * st["p200"]
    p_vol = 7.5 * clamp((st["vol"] - 0.8) / 0.4, 0, 1) + 7.5 * clamp(st["near_hi"] / 0.6, 0, 1)
    parts = {"rs": p_rs, "consistency": p_con, "breadth": p_br, "volume": p_vol}
    if catalyst is None:
        parts["catalyst"] = None
        total = sum(parts[k] for k in ("rs", "consistency", "breadth", "volume")) * 100 / 85
    else:
        parts["catalyst"] = catalyst["points"]
        total = p_rs + p_con + p_br + p_vol + catalyst["points"]
    parts["total"] = round(total, 2)
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
