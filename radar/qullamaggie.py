"""Plan de operación según las reglas públicas de Qullamaggie (Kristjan Kullamägi).

Reglas codificadas (setup de ruptura, "breakout"):
  1. Subida previa fuerte: ≥ 30% en los 1-3 meses anteriores a la base.
  2. Consolidación ordenada de 2 semanas a 2 meses (se aceptan flags de 5-9 sesiones),
     con mínimos crecientes y el precio "surfeando" las SMA10 y SMA20 ascendentes.
  3. ADR ≥ 5% (valores volátiles: más recorrido por unidad de capital).
  4. Liquidez ≥ 20 M USD diarios y fuerza relativa entre el 10% mejor del universo.
  5. Mercado: Nasdaq 100 sobre sus SMA10 y SMA20 ascendentes para operar con normalidad.
Entrada: ruptura del máximo del rango de apertura (ORH) de 1 o 5 minutos (60 min si el rango
es amplio) el día que el precio supera la resistencia de la base.
Stop: mínimo del día de entrada; no se entra si queda a más de 1 ADR del precio de entrada.
Riesgo por operación: 0,25-1% de la cuenta (habitual 0,3-0,5%).
Salidas: vender 1/3-1/2 a los 3-5 días en fuerza y subir el stop al precio de entrada;
el resto se vende al primer cierre bajo la SMA10 (valores rápidos, ADR ≥ 5%) o la SMA20.

Episodic pivot (EP): hueco al alza ≥ 10% con volumen ≥ 3x por un catalizador (resultados,
noticias), preferiblemente tras meses lateral. Entrada en el ORH del día del hueco o de los
días siguientes; stop en el mínimo del día; mismas salidas.
"""
from __future__ import annotations

from .metrics import Metrics

HARD = ("prior_move", "adr", "base", "liquidity")


def market_filter(m: Metrics | None) -> dict:
    """Semáforo de mercado con el Nasdaq 100 frente a sus SMA10 y SMA20."""
    if m is None or not m.s10 or not m.s20:
        return {"light": "sin datos", "text": "Sin datos del Nasdaq 100"}
    above10, above20 = m.C > m.s10, m.C > m.s20
    rising = bool(m.s10up) and bool(m.s20up)
    if above10 and above20 and rising:
        return {"light": "verde", "text": "Nasdaq 100 sobre SMA10 y SMA20 ascendentes: operar rupturas con normalidad",
                "s10": m.s10, "s20": m.s20, "close": m.C}
    if above20:
        return {"light": "ámbar", "text": "Nasdaq 100 sobre la SMA20 pero sin tendencia clara en las cortas: tamaño reducido",
                "s10": m.s10, "s20": m.s20, "close": m.C}
    return {"light": "rojo", "text": "Nasdaq 100 bajo SMA10 y SMA20: no abrir rupturas nuevas o hacerlo con tamaño mínimo",
            "s10": m.s10, "s20": m.s20, "close": m.C}


def evaluate(m: Metrics, state: str, mdv_usd: float, rs_pct: float, market: dict) -> dict:
    """Lista de comprobación, veredicto y plan de entrada y salida para una candidata."""
    checks = []

    def add(key: str, ok: bool | None, label: str, value: str):
        checks.append({"key": key, "ok": ok, "hard": key in HARD, "label": label, "value": value})

    pct = lambda x: f"{x * 100:.1f}%".replace(".", ",")  # noqa: E731
    add("prior_move", m.prior_move >= 0.30, "Subida previa ≥ 30% en 1-3 meses", pct(m.prior_move))
    add("base", 5 <= m.blen <= 60 and m.depth <= 0.35, "Base de 2 semanas a 2 meses (flag ≥ 5 sesiones)",
        f"{m.blen} sesiones, {pct(m.depth)} de profundidad")
    add("adr", m.adr_pct >= 0.05, "ADR ≥ 5%", pct(m.adr_pct))
    add("liquidity", mdv_usd >= 20e6, "Liquidez ≥ 20 M USD/día", f"{mdv_usd / 1e6:.0f} M USD".replace(".", ","))
    add("higher_lows", m.higher_lows, "Mínimos crecientes en la base",
        "sí" if m.higher_lows else ("no" if m.higher_lows is False else "base corta"))
    surf = bool(m.s10 and m.s20 and m.C > m.s20 and m.s10 > m.s20 and m.s10up and m.s20up)
    add("ma_surf", surf, "Sobre SMA10 y SMA20 ascendentes", "sí" if surf else "no")
    add("rs", rs_pct >= 0.90, "Fuerza relativa en el 10% superior", f"percentil {rs_pct * 100:.0f}")

    hard_fail = [c for c in checks if c["hard"] and c["ok"] is False]
    soft_fail = [c for c in checks if not c["hard"] and c["ok"] is False]
    if hard_fail:
        verdict = "No cumple"
    elif soft_fail or market.get("light") != "verde":
        verdict = "Con reservas"
    else:
        verdict = "Cumple"

    adr = m.adr_pct
    ext = m.C / m.P - 1
    if state in ("CONFIRMADA", "TEMPRANA") and ext > adr:
        trigger, entry_note = None, "Ya está a más de 1 ADR de la resistencia: no perseguir; esperar un nuevo rango o flag"
    elif state in ("CONFIRMADA", "TEMPRANA"):
        trigger = m.high
        entry_note = "Ruptura ya iniciada: entrar solo si supera el máximo de hoy en el rango de apertura (ORH) de 1-5 min"
    elif state in ("PRE-BREAKOUT", "RETEST"):
        trigger = m.P
        entry_note = "Entrar el día que supere la resistencia, en la ruptura del rango de apertura (ORH) de 1-5 min"
    else:
        trigger, entry_note = None, "Sin setup de entrada"
    stop_max = trigger * (1 - adr) if trigger else None
    trail = "SMA10" if adr >= 0.05 else "SMA20"
    trail_val = m.s10 if trail == "SMA10" else m.s20
    return {
        "verdict": verdict, "checks": checks, "adr_pct": adr,
        "trigger": trigger, "entry_note": entry_note,
        "entry_timeframe": "Intradía: ORH de 1 o 5 minutos (60 minutos si el rango de apertura es amplio)",
        "stop_rule": "Mínimo del día de entrada", "stop_max": stop_max,
        "stop_note": f"No entrar si el mínimo del día queda a más de 1 ADR ({pct(adr)}) del precio de entrada",
        "sell_plan": [
            "Vender 1/3-1/2 a los 3-5 días de la entrada, aprovechando la fuerza",
            "Subir el stop del resto al precio de entrada",
            f"Vender el resto al primer cierre diario bajo la {trail}",
        ],
        "trail_ma": trail, "trail_value": trail_val,
        "risk_rule": "Riesgo por operación 0,25-1% de la cuenta (habitual 0,3-0,5%)",
        "horizon": "Setup en gráfico diario · entrada intradía · gestión diaria · días a semanas",
    }


def episodic_pivot(m: Metrics) -> dict | None:
    """Detecta un EP en la última sesión: hueco ≥ 10%, volumen ≥ 3x y cierre en la mitad alta."""
    if m.gap < 0.10 or (m.rvol or 0) < 3 or m.day_pos < 0.5:
        return None
    return {
        "gap": m.gap, "rvol": m.rvol, "close": m.C, "high": m.high, "low": m.low, "adr_pct": m.adr_pct,
        "plan": "Día 2 o siguientes: comprar la ruptura del máximo del rango de apertura (ORH) de 1-5 min; "
                "stop en el mínimo del día; vender 1/3-1/2 a los 3-5 días y el resto con la SMA10/SMA20",
    }
