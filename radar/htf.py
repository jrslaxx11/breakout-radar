"""High tight flag ("high tide flag" en sus directos): el setup favorito de Qullamaggie.

Lo describe así en su Swing Trading School: un movimiento enorme en pocas semanas, un retroceso
ordenado que se apoya en las medias de 10 y 20 sesiones, mínimos crecientes, un rango que se estrecha
y la ruptura de ese rango. "Si solo aprendes un setup, que sea este". No necesita estar en máximos
históricos: lo que importa es el impulso reciente.

Umbrales calibrados con sus operaciones (el mismo estudio que radar/stars.py: 704 rupturas suyas
frente a 141.000 rupturas normales de los mismos valores):
- Mástil: subida ≥ 90% desde el mínimo de las 40 sesiones previas al máximo (unas 8 semanas).
- Bandera: de 5 a 30 sesiones desde el máximo y corrección ≤ 35% desde el máximo (en sus casos,
  mediana de 13 sesiones y 22%; en valores tan rápidos la bandera puede ser más profunda que el
  20-25% clásico: "profunda" si pasa del 25%). Con 3-4 sesiones se muestra como bandera en formación.
- Resultado, medido con este mismo código la víspera de cada ruptura: el 19,5% de sus rupturas tiene
  esta forma frente al 2,2% de las rupturas normales (9 veces más). En rupturas normales con esta
  forma, el 34% sube más de un 20% en 20 sesiones y el 7,0% más de un 50% (13% y 1,5% en las demás).

docs/engine.js replica este archivo (prueba de paridad en tests/test_js_parity.py).
"""
from __future__ import annotations

from .metrics import Metrics

DEFAULTS = {"pole_min": 0.90, "flag_forming": 3, "flag_min": 5, "flag_max": 30, "depth_max": 0.35,
            "depth_classic": 0.25}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def evaluate(m: Metrics, cfg: dict | None = None) -> dict | None:
    """Mástil y bandera si la consolidación actual es un high tight flag; None si no lo es."""
    p = m.pole or {}
    q = {**DEFAULTS, **(cfg or {})}
    if not p or p["pole"] < q["pole_min"] or not (q["flag_forming"] <= p["flag_len"] <= q["flag_max"]) \
            or p["depth"] > q["depth_max"]:
        return None
    if p["flag_len"] < q["flag_min"]:
        kind = "en formación"
    elif p["depth"] <= q["depth_classic"]:
        kind = "clásica"
    else:
        kind = "profunda"
    text = (f"Mástil +{_pct(p['pole'])} en {p['pole_len']} sesiones; bandera de {p['flag_len']} sesiones "
            f"que corrige un {_pct(p['depth'])} desde el máximo")
    return {**p, "kind": kind, "text": text}


def constants() -> dict:
    return {**DEFAULTS, "pole_days": 40}
