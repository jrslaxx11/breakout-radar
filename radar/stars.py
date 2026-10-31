"""Puntuación de 1 a 5 estrellas de un setup de ruptura al estilo Qullamaggie.

Calibrada con sus propias operaciones: 704 rupturas de las 1.212 capturas de su archivo de swing
trading (las demás son valores que ya no cotizan) medidas con datos diarios y comparadas con 141.000
rupturas normales de esos mismos valores (cierre sobre el máximo de 10 sesiones). Los rasgos y su
peso salen de una regresión logística sobre tramos, redondeada a puntos enteros; los tramos y los
criterios son los que él repite en sus directos ("five star setup": gran subida, valor rápido, las
medias de 10 y 20 alcanzan al precio, se apoya en la de 10, rango estrecho, volumen seco, primeras bases).

Resultado del estudio (rupturas en tendencia, sobre la SMA50 ascendente):
- 5 estrellas: 23% de sus setups frente al 2,6% de las rupturas normales; ≥ 4: 51% frente al 12%.
- En rupturas normales (sin sus operaciones), las 5 estrellas suben > 50% en 20 sesiones el 10,8%
  de las veces y las de 1 estrella el 0,6%.

Todas las distancias y rangos van en ADR del propio valor (ver radar/metrics.py: _setup), medidos el
último día de la base: hoy si aún no ha roto, la víspera de la ruptura si ya rompió.
docs/engine.js replica este archivo (prueba de paridad en tests/test_js_parity.py).
"""
from __future__ import annotations

from .metrics import Metrics

MAX_POINTS = 66
# (puntos mínimos, estrellas)
STAR_STEPS = ((50, 5.0), (45, 4.5), (40, 4.0), (35, 3.5), (30, 3.0), (25, 2.5), (20, 2.0), (15, 1.5))
PILLARS = (
    ("lider", "Gran subida previa", 20),
    ("velocidad", "Valor rápido (ADR)", 12),
    ("tendencia", "Tendencia limpia", 14),
    ("medias", "Las medias alcanzan al precio", 12),
    ("compresion", "Compresión antes de romper", 8),
)
THEME_BONUS = 0.5


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _adr(x: float) -> str:
    return f"{x:+.1f} ADR".replace(".", ",")


def _num(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def stars_for(points: float) -> float:
    for lo, st in STAR_STEPS:
        if points >= lo:
            return st
    return 1.0


def rate(m: Metrics, theme_hot: bool = False) -> dict | None:
    """Estrellas del setup, puntos por bloque y el detalle de cada criterio."""
    s = m.setup or {}
    if not s:
        return None
    items = []

    def add(pillar: str, key: str, label: str, pts: int, mx: int, value: str):
        items.append({"pillar": pillar, "key": key, "label": label, "pts": pts, "max": mx, "value": value})

    mm = max(x for x in (m.prior_move, s.get("mom3")) if x is not None)
    add("lider", "move", "Subida previa (máximo entre la subida a la base y la de 3 meses desde el mínimo)",
        20 if mm >= 1.5 else 14 if mm >= 0.75 else 9 if mm >= 0.30 else 0, 20,
        f"+{_pct(mm)} (9 pts ≥ 30%, 14 ≥ 75%, 20 ≥ 150%)")
    adr = s["adr"]
    add("velocidad", "adr", "ADR de 20 sesiones", 12 if adr >= 0.08 else 7 if adr >= 0.05 else 0, 12,
        f"{_num(adr * 100)}% (7 pts ≥ 5%, 12 ≥ 8%)")
    add("tendencia", "sp", "SMA20 al menos 1 ADR por encima de la SMA50", 7 if s["sp"] >= 1.0 else 0, 7,
        _adr(s["sp"]))
    add("tendencia", "s20up", "SMA20 ascendente", 3 if s["s20up"] else 0, 3, "sí" if s["s20up"] else "no")
    lin = s.get("lin")
    add("tendencia", "lin", "Subida previa lineal (movimiento neto ≥ 40% del recorrido diario)",
        4 if (lin or 0) >= 0.4 else 0, 4, "sin datos" if lin is None else f"{_pct(lin)}")
    add("medias", "d10", "Cierre cerca de la SMA10", 4 if s["d10"] <= 0.5 else 2 if s["d10"] <= 1.0 else 0, 4,
        f"{_adr(s['d10'])} (4 pts ≤ 0,5; 2 ≤ 1)")
    add("medias", "d20", "Cierre a ≤ 1 ADR de la SMA20", 1 if s["d20"] <= 1.0 else 0, 1, _adr(s["d20"]))
    add("medias", "lo10", "Se apoya en la SMA10: algún mínimo de las 3 últimas sesiones la toca o la perfora",
        7 if s["lo10"] <= 0 else 0, 7, _adr(s["lo10"]))
    add("compresion", "t3", "Rango de las 3 últimas sesiones ≤ 1 ADR", 2 if s["t3"] <= 1.0 else 0, 2,
        f"{_num(s['t3'])} ADR")
    add("compresion", "t5", "Rango de las 5 últimas sesiones ≤ 1,25 ADR", 2 if s["t5"] <= 1.25 else 0, 2,
        f"{_num(s['t5'])} ADR")
    add("compresion", "rng", "Vela de la víspera estrecha (≤ 0,75 ADR)", 2 if s["rng"] <= 0.75 else 0, 2,
        f"{_num(s['rng'])} ADR")
    vd = s.get("vd5")
    add("compresion", "vd5", "Volumen seco: media de 5 sesiones ≤ 70% de la de 50",
        2 if vd is not None and vd <= 0.7 else 0, 2, "sin datos" if vd is None else _pct(vd))
    pen = []
    if s["bases"] >= 4:
        pen.append({"key": "bases", "label": f"{s['bases']} bases ya completadas desde el mínimo de 6 meses (ruptura tardía)", "pts": -4})
    if s["blen"] < 5:
        pen.append({"key": "blen", "label": f"Consolidación de solo {s['blen']} sesiones", "pts": -6})
    pillars = {k: sum(i["pts"] for i in items if i["pillar"] == k) for k, _, _ in PILLARS}
    total = sum(pillars.values()) + sum(p["pts"] for p in pen)
    chart = stars_for(total)
    bonus = THEME_BONUS if theme_hot and chart < 5 else 0.0
    return {
        "stars": min(5.0, chart + bonus), "chart_stars": chart, "theme_bonus": bonus > 0,
        "points": total, "max": MAX_POINTS, "pillars": pillars, "items": items, "penalties": pen,
        "bases": s["bases"],
    }


def constants() -> dict:
    """Textos y tramos comunes (se envían una sola vez al dashboard)."""
    return {
        "max": MAX_POINTS, "steps": [list(x) for x in STAR_STEPS], "theme_bonus": THEME_BONUS,
        "pillars": [{"key": k, "label": lab, "max": mx} for k, lab, mx in PILLARS],
    }
