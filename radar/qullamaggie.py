"""Setup de ruptura de Qullamaggie (Kristjan Kullamägi) traducido a reglas objetivas.

Fuente principal: "3 TIMELESS setups that have made me TENS OF MILLIONS!" (qullamaggie.com, 2021).
Búsqueda: el 1-2% de valores que más suben a 1, 3 y 6 meses (escáneres de su comunidad: ADR > 5%).
Setup en tres pasos:
  1. Subida grande en los últimos 1-3 meses: 30-100% o más, en días o pocas semanas.
  2. Retroceso ordenado y consolidación con mínimos crecientes y rango que se estrecha, normalmente
     de 2 semanas a 2 meses, "surfeando" las SMA10 y SMA20 ascendentes (a veces la SMA50).
  3. Expansión de rango (ruptura) del borde superior: canal plano, triángulo simétrico o
     descendente, flag. Ese borde se calcula en radar/metrics.py (_base_at).
Entrada: máximo de la primera vela de 1, 5 o 60 minutos (ORH), o en el diario cuando empieza a romper.
Stop: mínimo del día, nunca más ancho que el ADR/ATR.
Salidas: vender 1/3-1/2 a los 3-5 días y subir el stop a la entrada; el resto, al primer cierre bajo
la SMA10 o la SMA20 según lo rápido que sea el valor (principiantes: SMA10).
Tamaño: posiciones del 10-20% de la cuenta, nunca más del 30% de un día para otro; riesgo 0,25-1%.

Los umbrales están en config/settings.yaml (sección `qullamaggie`); docs/engine.js replica este archivo.
"""
from __future__ import annotations

from .metrics import Metrics

DEFAULTS = {"top_pct": 0.02, "adr_min": 0.05, "prior_move_min": 0.30, "base_min": 5, "base_max": 42,
            "retrace_max": 0.50, "tight_max": 0.80}
HARD = ("leader", "adr", "prior_move", "base")


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%".replace(".", ",")


def _sgn(x: float) -> str:
    return f"{x * 100:+.0f}%"


def perf_cutoffs(rows: list, top_pct: float) -> dict:
    """Rentabilidad mínima para estar en el `top_pct` del universo a 1, 3 y 6 meses."""
    out = {}
    for k in ("r1m", "r3m", "r6m"):
        vals = sorted(v for v in (getattr(m, k) for m in rows) if v is not None)
        out[k] = vals[min(len(vals) - 1, int(len(vals) * (1 - top_pct)))] if vals else None
    return out


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


def evaluate(m: Metrics, state: str, market: dict, perf_cut: dict | None = None, qcfg: dict | None = None) -> dict:
    """Lista de comprobación, veredicto y plan de entrada y salida."""
    q = {**DEFAULTS, **(qcfg or {})}
    checks = []

    def add(key: str, ok: bool | None, label: str, value: str):
        checks.append({"key": key, "ok": ok, "hard": key in HARD, "label": label, "value": value})

    top = f"{q['top_pct'] * 100:.0f}%"
    rets = (("1 m", m.r1m, "r1m"), ("3 m", m.r3m, "r3m"), ("6 m", m.r6m, "r6m"))
    if perf_cut:
        hits = [f"{lab} {_sgn(r)}" for lab, r, k in rets if r is not None and perf_cut.get(k) is not None and r >= perf_cut[k]]
        add("leader", bool(hits), f"Entre el {top} que más sube a 1, 3 o 6 meses",
            ("sí: " + ", ".join(hits)) if hits else "no: " + ", ".join(f"{lab} {_sgn(r)}" for lab, r, _ in rets if r is not None))
    else:
        add("leader", None, f"Entre el {top} que más sube a 1, 3 o 6 meses", "sin datos del universo")
    add("adr", m.adr_pct >= q["adr_min"], f"ADR ≥ {_pct(q['adr_min'], 0)} (valor rápido)", _pct(m.adr_pct))
    add("prior_move", m.prior_move >= q["prior_move_min"], f"Subida previa ≥ {_pct(q['prior_move_min'], 0)} en 1-3 meses",
        _pct(m.prior_move))
    add("base", q["base_min"] <= m.blen <= q["base_max"], "Consolidación de 2 semanas a 2 meses (flag desde 5 sesiones)",
        f"{m.blen} sesiones")
    add("orderly", None if m.retrace is None else m.retrace <= q["retrace_max"],
        f"Retroceso ordenado (corrige ≤ {_pct(q['retrace_max'], 0)} de la subida)",
        "sin datos" if m.retrace is None else f"corrige el {_pct(m.retrace, 0)}")
    add("higher_lows", m.higher_lows, "Mínimos crecientes en la base",
        "sí" if m.higher_lows else ("no" if m.higher_lows is False else "base corta"))
    add("tight", None if m.tight_ratio is None else m.tight_ratio <= q["tight_max"], "Rango que se estrecha",
        "base corta" if m.tight_ratio is None else f"rango reciente al {_pct(m.tight_ratio, 0)} del inicial")
    surf20 = bool(m.s20 and m.C >= m.s20 and m.s20up and m.s10up)
    surf50 = bool(m.s50 and m.C >= m.s50 and m.s50up)
    add("ma_surf", surf20 or surf50, "Surfea medias ascendentes (SMA10 y SMA20, o SMA50)",
        "SMA10 y SMA20" if surf20 else ("SMA50" if surf50 else "no"))

    hard_fail = any(c["hard"] and c["ok"] is False for c in checks)
    soft_fail = any(not c["hard"] and c["ok"] is False for c in checks)
    if hard_fail:
        verdict = "No cumple"
    elif soft_fail or market.get("light") != "verde":
        verdict = "Con reservas"
    else:
        verdict = "Cumple"

    adr = m.adr_pct
    ext = m.C / m.P - 1
    if state in ("CONFIRMADA", "TEMPRANA") and ext > adr:
        trigger, entry_note = None, "Ya está a más de 1 ADR del nivel de ruptura: no perseguir; esperar una nueva consolidación"
    elif state in ("CONFIRMADA", "TEMPRANA"):
        trigger = m.high
        entry_note = "Ruptura ya iniciada: entrar solo si supera el máximo de hoy en el rango de apertura (ORH)"
    elif state in ("PRE-BREAKOUT", "RETEST"):
        trigger = m.P
        entry_note = ("Entrar el día que supere la resistencia descendente (su valor baja cada sesión), en el ORH"
                      if m.level_kind == "línea" else "Entrar el día que supere la resistencia, en el ORH")
    else:
        trigger, entry_note = None, "Sin setup de entrada"
    stop_max = trigger * (1 - adr) if trigger else None
    trail = "SMA10" if adr >= q["adr_min"] else "SMA20"
    return {
        "verdict": verdict, "checks": checks, "adr_pct": adr,
        "trigger": trigger, "entry_note": entry_note, "stop_max": stop_max,
        "trail_ma": trail, "trail_value": m.s10 if trail == "SMA10" else m.s20,
    }


def constants() -> dict:
    """Textos comunes a todas las acciones (se envían una sola vez al dashboard)."""
    return {
        "entry_timeframe": "Intradía: máximo de la primera vela de 1, 5 o 60 minutos (la de 60 solo cubre 9:30-10:00), "
                           "o en el gráfico diario cuando empieza a romper",
        "stop_rule": "Mínimo del día de entrada",
        "stop_note": "Nunca más ancho que el ADR (o el ATR) del valor; si lo es, no hay entrada",
        "sell_plan": [
            "Vender 1/3-1/2 a los 3-5 días de la entrada",
            "Subir el stop del resto al precio de entrada",
            "Vender el resto al primer cierre diario bajo la SMA10 o la SMA20, según lo rápido que sea el valor "
            "(principiantes: SMA10)",
        ],
        "risk_rule": "Riesgo por operación 0,25-1% de la cuenta; posición habitual 10-20%, nunca más del 30% de un día para otro",
        "horizon": "Setup en gráfico diario · entrada intradía · gestión diaria · días a semanas",
    }
