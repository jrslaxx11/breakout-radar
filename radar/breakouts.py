"""Clasificación de rupturas, nivel de invalidación, puntuación y riesgo de cada acción."""
from __future__ import annotations

from dataclasses import dataclass

from .metrics import Metrics

CONFIRMED, EARLY, PRE, RETEST, EXTENDED, BASE, DISCARDED = (
    "CONFIRMADA", "TEMPRANA", "PRE-BREAKOUT", "RETEST", "EXTENDIDA", "EN BASE", "DESCARTADA")
ACTIONABLE = (CONFIRMED, EARLY, PRE, RETEST)


@dataclass
class Classification:
    state: str
    why: str = ""


def classify(m: Metrics, mdv_usd: float | None, price_usd: float | None, cfg: dict,
             filters: dict) -> Classification:
    """Asigna uno de los estados de la fase 5 con reglas explícitas (ver README)."""
    if mdv_usd is None or mdv_usd < filters["min_mdv_usd"] or (price_usd or 0) < filters["min_price_usd"]:
        return Classification(DISCARDED, "liquidez o precio insuficiente")
    # Precio anclado (típico de una OPA en efectivo): volatilidad mínima y rango estrecho.
    if m.atr_pct < cfg["pinned_atr_pct"] and m.tight < 0.025:
        return Classification(DISCARDED, "precio anclado (posible OPA)")
    if m.s50 and m.C < m.s50 and m.s50up is False:
        return Classification(DISCARDED, "bajo SMA50 descendente")

    P, C = m.P, m.C
    if C > P:
        ext = C / P - 1
        if ext > cfg["extended_pct"] or (m.s20 and (C - m.s20) > cfg["extended_atr_over_sma20"] * m.atr):
            return Classification(EXTENDED, f"+{ext * 100:.1f}% sobre el nivel de ruptura".replace(".", ","))
        if m.cross == 0:
            if (m.rvol or 0) >= cfg["rvol_confirm"] and m.day_pos >= 0.5:
                return _short_base(Classification(CONFIRMED), m, cfg)
            why = "volumen < 1,5x" if (m.rvol or 0) < cfg["rvol_confirm"] else "cierre en la mitad baja del rango"
            return _short_base(Classification(EARLY, why), m, cfg)
        if m.max_close_since and m.max_close_since / P - 1 >= cfg["retest_band"] and ext <= cfg["retest_band"]:
            return Classification(RETEST, "vuelve al nivel de ruptura")
        if (m.rvol_cross or 0) >= cfg["rvol_confirm"] and ext <= 0.06:
            return _short_base(Classification(CONFIRMED, f"ruptura hace {m.cross} ses."), m, cfg)
        rc = f"{m.rvol_cross:.1f}".replace(".", ",") if m.rvol_cross else "?"
        return _short_base(Classification(EARLY, f"cruce hace {m.cross} ses. con {rc}x volumen"), m, cfg)

    dist = P / C - 1
    if m.any_closed_above and C < P * (1 - cfg["failed_break_pct"]):
        return Classification(DISCARDED, "ruptura fallida")
    if m.any_closed_above:
        return Classification(RETEST, "perdió el nivel de ruptura tras cruzarlo")
    above50 = bool(m.s50 and C > m.s50)
    if m.blen < cfg["flag_min_base"]:
        # Máximo muy reciente: todavía no hay consolidación que romper.
        if m.s20 and (C - m.s20) > cfg["extended_atr_over_sma20"] * m.atr:
            return Classification(EXTENDED, "en plena subida, sin consolidación")
        if above50:
            return Classification(BASE, f"base en formación ({m.blen} ses.)")
    if dist <= cfg["pre_dist"] and m.blen >= cfg["pre_min_base"] and m.depth <= cfg["pre_max_depth"] and above50:
        return Classification(PRE)
    if dist <= cfg["pre_dist"] and m.blen >= cfg["flag_min_base"] and m.depth <= cfg["flag_max_depth"] and above50:
        return Classification(PRE, f"flag corto ({m.blen} ses.)")
    if dist <= cfg["base_max_dist"] and above50:
        return Classification(BASE, f"{dist * 100:.1f}% bajo el nivel de ruptura".replace(".", ","))
    return Classification(DISCARDED, "bajo SMA50" if not above50 else f"{dist * 100:.0f}% bajo el nivel de ruptura")


def _short_base(c: Classification, m: Metrics, cfg: dict) -> Classification:
    if m.blen < cfg["pre_min_base"]:
        c.why = (c.why + "; " if c.why else "") + f"base corta ({m.blen} ses.)"
    return c


def invalidation(m: Metrics, state: str) -> float | None:
    """Nivel técnico cuyo cierre por debajo invalida la hipótesis."""
    if state in (CONFIRMED, EARLY, RETEST):
        return max(m.P - m.atr, min(m.lo5, m.P * 0.97))
    if state in (PRE, BASE):
        return m.lo5 if (m.C - m.lo10) > 2.5 * m.atr else m.lo10
    if state == EXTENDED:
        return m.s20
    return None


def score(m: Metrics, state: str, rs_pct: float, mdv_usd: float, catalyst: float | None) -> dict:
    """Puntuación 0-100 (fase 6). Si el catalizador no está disponible se redistribuye su peso."""
    p_rs = 25 * (rs_pct or 0)

    dep = 8 if m.depth <= .15 else 6 if m.depth <= .25 else 3 if m.depth <= .35 else 0
    blen = 4 if m.blen >= 15 else 3 if m.blen >= 10 else 1
    tr = m.tight / m.atr_pct if m.atr_pct else 99
    tight = 5 if tr <= 4.5 else 3 if tr <= 6.5 else 1
    vd = m.vdry if m.vdry is not None else 1.2
    dry = 3 if vd <= 0.9 else 2 if vd <= 1.1 else 1
    hi = 5 if m.dhi >= -0.05 else 3 if m.dhi >= -0.15 else 1 if m.dhi >= -0.25 else 0
    p_base = dep + blen + tight + dry + hi

    rvol = m.rvol or 0
    if state == CONFIRMED and m.cross:
        p_bo = 15 + (3 if (m.rvol_cross or 0) >= 2 else 0)
    else:
        p_bo = {
            CONFIRMED: 17 + (3 if rvol >= 2 else 0),
            EARLY: 10 + (2 if rvol >= 1.2 else 0),
            RETEST: 12 + (2 if rvol < 1 else 0),
            PRE: 7 + (2 if vd < 0.9 else 0) + (2 if (m.P / m.C - 1) <= 0.02 else 0),
            EXTENDED: 5, BASE: 3, DISCARDED: 0,
        }[state]

    p_tr = ((3 if m.s20 and m.C > m.s20 else 0) + (3 if m.s50 and m.C > m.s50 else 0)
            + (3 if m.s200 and m.s50 and m.s50 > m.s200 else 0) + (3 if m.s200up else 0)
            + (3 if m.s150up and m.s150 and m.C > m.s150 else 0))

    p_liq = 10 if mdv_usd >= 50e6 else 8 if mdv_usd >= 20e6 else 6 if mdv_usd >= 10e6 else 4 if mdv_usd >= 5e6 else 0
    if m.n < 200:
        p_liq -= 2

    parts = {"rs": p_rs, "base": p_base, "breakout": p_bo, "trend": p_tr, "liquidity": p_liq}
    if catalyst is None:
        total = sum(parts.values()) * 100 / 95
        parts["catalyst"] = None
    else:
        parts["catalyst"] = catalyst
        total = sum(v for v in parts.values() if v is not None)
    parts["total"] = round(total, 2)
    return parts


def risk(m: Metrics, inv: float | None, next_earnings_days: int | None, pending: bool,
         mdv_usd: float, rcfg: dict) -> tuple[str, int]:
    """Etiqueta de riesgo separada de la puntuación."""
    pts = 3 if m.atr_pct >= 0.07 else 2 if m.atr_pct >= 0.05 else 1 if m.atr_pct >= 0.03 else 0
    if pending:
        pts += 3
    elif next_earnings_days is not None and 0 <= next_earnings_days <= rcfg["earnings_near_days"]:
        pts += 2
    elif next_earnings_days is not None and 0 <= next_earnings_days <= rcfg["earnings_mid_days"]:
        pts += 1
    if inv:
        inv_atr = (m.C - inv) / m.atr if m.atr else 0
        if inv_atr > 2.5 or (m.C / inv - 1) > 0.10:
            pts += 1
    if mdv_usd < 20e6:
        pts += 1
    return ("Alto" if pts >= 4 else "Medio" if pts >= 2 else "Bajo"), pts


def conditions(m: Metrics, state: str, inv: float | None) -> tuple[str, str]:
    """Condición que confirmaría la hipótesis y condición que la invalidaría."""
    def f(x: float) -> str:
        d = 0 if x >= 1000 else 2
        return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    v15 = 1.5 * (m.v20 or 0)
    vol_txt = f"{v15 / 1e6:.2f} M".replace(".", ",") if v15 >= 1e5 else f"{v15:,.0f}".replace(",", ".")
    inv_txt = f"Cierre < {f(inv)}" if inv else ""
    if state == CONFIRMED:
        return f"Cierres sostenidos > {f(m.P)} con volumen ≥ media", inv_txt
    if state == EARLY:
        return f"Nuevo cierre > {f(max(m.P, m.C))} con ≥ {vol_txt} (1,5x)", inv_txt
    if state == RETEST:
        if m.C > m.P:
            return f"Rebote desde {f(m.P)} con volumen creciente", inv_txt
        return f"Recuperar y cerrar > {f(m.P)}", inv_txt
    if state in (PRE, BASE):
        where = " (resistencia descendente)" if m.level_kind == "línea" else ""
        return f"Cierre > {f(m.P)}{where} con ≥ {vol_txt} (1,5x)", inv_txt
    if state == EXTENDED:
        return "Esperar base nueva o retroceso a la SMA20", f"Cierre < SMA20 ({f(m.s20)})" if m.s20 else ""
    return "", ""
