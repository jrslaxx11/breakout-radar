"""Histórico diario y lógica NUEVA / CONTINÚA / MEJORA / DETERIORA / ELIMINADA."""
from __future__ import annotations

import json
from pathlib import Path

from .config import HISTORY_DIR

STATE_RANK = {"DESCARTADA": 0, "EN BASE": 1, "EXTENDIDA": 2, "PRE-BREAKOUT": 2,
              "RETEST": 3, "TEMPRANA": 3, "CONFIRMADA": 4}


def previous_snapshot(before: str) -> dict | None:
    """Última foto anterior a la fecha `before` (AAAA-MM-DD)."""
    if not HISTORY_DIR.exists():
        return None
    files = sorted(p for p in HISTORY_DIR.glob("????-??-??.json") if p.stem < before)
    if not files:
        return None
    return json.loads(files[-1].read_text())


def daily_status(sym: str, cur: dict, prev: dict | None) -> tuple[str, float | None]:
    """Compara una candidata presentada hoy con la foto anterior."""
    if not prev or sym not in prev.get("watchlist", {}):
        return "NUEVA", None
    p = prev["watchlist"][sym]
    d_score = cur["score"] - p["score"]
    up = STATE_RANK.get(cur["state"], 0) > STATE_RANK.get(p["state"], 0)
    down = STATE_RANK.get(cur["state"], 0) < STATE_RANK.get(p["state"], 0)
    if up or d_score >= 3 or (cur["state"] == "CONFIRMADA" and p["state"] != "CONFIRMADA"):
        return "MEJORA", p["score"]
    if down or d_score <= -3 or (cur.get("rs_pct", 0) - p.get("rs_pct", 0)) <= -0.10:
        return "DETERIORA", p["score"]
    return "CONTINÚA", p["score"]


def removed(today_watch: dict, prev: dict | None, analysed: dict) -> list[dict]:
    """Valores que estaban ayer en la watchlist y hoy ya no cumplen los criterios."""
    if not prev:
        return []
    out = []
    for sym, p in prev.get("watchlist", {}).items():
        if sym in today_watch:
            continue
        a = analysed.get(sym)
        reason = "fuera del top de su temática"
        if a is None:
            reason = "sin datos hoy"
        elif a.get("state") not in ("CONFIRMADA", "TEMPRANA", "PRE-BREAKOUT", "RETEST"):
            reason = f"{a.get('state', '').lower()}: {a.get('why') or 'estructura no operable'}"
        elif a.get("theme") not in today_watch.get("__themes__", []):
            reason = "su temática salió de la selección"
        out.append({"sym": sym, "theme": p.get("theme"), "prev_score": p.get("score"),
                    "prev_state": p.get("state"), "reason": reason})
    return out


def write_snapshot(date: str, payload: dict) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    index = sorted(p.stem for p in HISTORY_DIR.glob("????-??-??.json"))
    (HISTORY_DIR / "index.json").write_text(json.dumps(index))
    return path
