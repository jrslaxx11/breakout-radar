"""Integración diaria del sistema de Martin Luk: universo, líderes, setups, ranking, régimen y control de calidad.

Lo llama radar/pipeline.py en dos pasos: `screen` (antes de consultar resultados, para que las candidatas
entren en la consulta) y `finalize` (después, para puntuar con las fechas de resultados).
"""
from __future__ import annotations

import csv
import logging
import time
from collections import Counter
from datetime import date

import numpy as np

from . import luk
from .config import CONFIG_DIR

log = logging.getLogger(__name__)
TRADES_FILE = CONFIG_DIR / "luk_trades.csv"
CONTEXT_ETFS = ("SPY", "QQQ", "IWM")


def load_trades(path=TRADES_FILE) -> list[dict]:
    """Entradas documentadas de Luk (config/luk_trades.csv) para medir la cobertura."""
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append({"sym": row["sym"].strip(), "date": (row.get("date") or "").strip() or None,
                        "setup": (row.get("setup") or "").strip(), "verified": (row.get("verified") or "").strip().lower() == "true",
                        "source": (row.get("source") or "").strip(), "note": (row.get("note") or "").strip()})
    return out


def _pct_ranks(vals: dict[str, float]) -> dict[str, float]:
    items = sorted((v, k) for k, v in vals.items() if v is not None and np.isfinite(v))
    n = len(items)
    return {k: (i + 1) / n for i, (_, k) in enumerate(items)} if n else {}


def screen(liquid: list[dict], prices: dict, settings: dict, mcaps: dict, is_us) -> dict:
    """Universo, líderes y setups de la sesión. `liquid`: filas líquidas del radar (con sym, info, group, m,
    mdv_usd, price_usd, scan, rsc, dup)."""
    t0 = time.time()
    q = luk.cfg_of(settings.get("luk"))
    rows = [r for r in liquid if not r["dup"] and is_us(r["sym"]) and r["sym"] in prices]
    uni, excl, flag_count, static_ok = {}, Counter(), Counter(), {}
    for r in rows:
        mc = mcaps.get(r["sym"])
        ok, why, flags = luk.universe_check(r["info"], r.get("group"), mc, r["price_usd"], r["mdv_usd"],
                                            r["m"].adr_pct, q)
        st_ok, _, _ = luk.universe_check(r["info"], r.get("group"), mc, float("inf"), float("inf"), float("inf"), q)
        static_ok[r["sym"]] = st_ok
        if ok:
            uni[r["sym"]] = {"row": r, "flags": flags, "mcap": mc}
            flag_count.update(flags)
        else:
            excl[why] += 1
    prepared: dict = {}

    def prep(sym):
        if sym not in prepared:
            prepared[sym] = luk.prepare(prices[sym], q)
        return prepared[sym]

    # Fuerza relativa del ranking: percentiles de la subida a 3 y 6 meses (cierre contra cierre) en el universo.
    p3, p6 = {}, {}
    for sym in uni:
        c = prices[sym]["Close"].dropna()
        if len(c) > 126:
            p3[sym], p6[sym] = float(c.iloc[-1] / c.iloc[-64] - 1), float(c.iloc[-1] / c.iloc[-127] - 1)
    r3, r6 = _pct_ranks(p3), _pct_ranks(p6)
    rs = {s: (r3[s] + r6[s]) / 2 for s in uni if s in r3 and s in r6}

    analyses: dict[str, dict] = {}
    for sym, u in uni.items():
        if not u["row"].get("scan"):
            continue
        P = prep(sym)
        a = luk.analyze(P, P["n"] - 1, q, True) if P else None
        if a:
            analyses[sym] = a
    leaders = {s for s, a in analyses.items() if a["leader"]}
    groups = Counter(uni[s]["row"].get("group") for s in leaders if uni[s]["row"].get("group"))

    # EP de hoy en todo el universo (no solo líderes): a vigilar para L1.
    for sym in uni:
        if sym in analyses:
            continue
        df = prices[sym]
        if len(df) < 60:
            continue
        o, c, v = (df[k].to_numpy(float) for k in ("Open", "Close", "Volume"))
        m50 = np.nanmean(v[-51:-1])
        if c[-2] > 0 and o[-1] / c[-2] - 1 >= q["ep_gap"] and m50 > 0 and v[-1] >= q["ep_vol_mult"] * m50:
            P = prep(sym)
            a = luk.analyze(P, P["n"] - 1, q, bool(uni[sym]["row"].get("scan"))) if P else None
            if a:
                analyses[sym] = a

    # Termómetro: los 100 valores del universo con más fuerza relativa (sin filtro de medias).
    top = sorted(uni, key=lambda s: -uni[s]["row"]["rsc"])[:q["health_top"]]
    hc = Counter()
    lists = {"sano": [], "dañado": [], "mixto": []}
    for sym in top:
        P = prep(sym)
        st = luk.health(P, P["n"] - 1, q) if P else "sin datos"
        hc[st] += 1
        if st in lists:
            lists[st].append(sym)
    counts = {"n": hc["sano"] + hc["dañado"] + hc["mixto"], "good": hc["sano"], "bad": hc["dañado"], "mixed": hc["mixto"],
              "good_syms": lists["sano"][:40], "bad_syms": lists["dañado"][:40], "mixed_syms": lists["mixto"][:40],
              "all_syms": top}
    ctx = {}
    for etf in CONTEXT_ETFS:
        if etf in prices:
            P = luk.prepare(prices[etf], q)
            if P:
                ctx[etf] = luk.context(P, P["n"] - 1, q)
    log.info("Luk: universo %d (fuera: %s), líderes %d, setups %d, %.1f s", len(uni), dict(excl), len(leaders),
             sum(1 for a in analyses.values() if a["setup"]), time.time() - t0)
    return {"cfg": q, "uni": uni, "analyses": analyses, "leaders": leaders, "groups": groups, "rs": rs,
            "prepared": prepared, "static_ok": static_ok,
            "regime": {"mode": luk.mode(counts, q), "counts": counts, "context": ctx},
            "universe": {"n": len(uni), "leaders": len(leaders), "excluded": dict(excl), "flags": dict(flag_count)}}


def finalize(st: dict, view_by: dict, today: date, hot: set) -> dict:
    """Ranking, niveles y listas de salida. `view_by`: fichas del radar (para resultados y nombre)."""
    q = st["cfg"]
    setups, l3, eps = [], [], []
    for sym, a in st["analyses"].items():
        u = st["uni"][sym]
        r = u["row"]
        v = view_by.get(sym) or {}
        nxt = v.get("next_earnings")
        es = luk.earnings_sessions(nxt, today)
        known = bool(nxt) or v.get("next_earnings_est") is not None
        g = r.get("group")
        theme_n = st["groups"].get(g, 0) if g else 0
        base = {
            "sym": sym, "name": v.get("name") or r["info"].get("name") or sym, "currency": v.get("currency") or "USD",
            "group": g, "group_name": v.get("group_name"), "theme_n": theme_n, "lead_group": theme_n >= 2,
            "hot": g in hot, "mcap": u["mcap"], "presented": bool(v.get("presented")), "next_earnings": nxt,
            "earn_sessions": es, "rs": st["rs"].get(sym), "uflags": u["flags"],
        }
        a["theme_n"] = theme_n
        if a["setup"] in luk.SETUPS:
            sc = luk.score(a, st["rs"].get(sym), theme_n, es, known, q)
            lv = luk.levels(a, q)
            a.update({**sc, **lv, "flags": u["flags"] + sc["flags"] + (["perforación: gatillo reclaim de la EMA 21"] if a["setup"] == "L1b" else [])})
            setups.append({**base, **_slim(a)})
        elif a["setup"] == "L3":
            lv = luk.levels(a, q)
            a.update({**lv, "flags": u["flags"] + (["resultados en %d sesiones" % es] if es is not None and es <= q["earnings_window"] else [])})
            l3.append({**base, **_slim(a)})
        if a["ep_today"]:
            eps.append({**base, **{k: a.get(k) for k in ("date", "close", "gap", "vol_x", "adr", "leader", "why", "setup")}})
    setups.sort(key=lambda x: -x["score"])
    for i, x in enumerate(setups):
        x["rank"] = i + 1
    l3.sort(key=lambda x: x["close"] / x["base_hi"] * -1)
    eps.sort(key=lambda x: -(x["gap"] or 0))
    return {"setups": setups[:q["max_list"]], "l3": l3[:q["max_l3"]], "ep": eps[:q["max_ep"]],
            "n_l1": sum(1 for x in setups if x["setup"] == "L1"), "n_l1b": sum(1 for x in setups if x["setup"] == "L1b")}


def stats(st: dict, liquid: list[dict], prices: dict, is_us, scan_pct: float, liq: dict) -> dict | None:
    """Tamaño de la lista diaria y cobertura de las entradas documentadas (no rompe la ejecución si falla)."""
    t0 = time.time()
    try:
        frames = {r["sym"]: prices[r["sym"]] for r in liquid if not r["dup"] and is_us(r["sym"]) and r["sym"] in prices}
        out = luk.history_stats(frames, st["static_ok"], st["cfg"], scan_pct, liq, load_trades(), st["prepared"])
        log.info("Luk: control de calidad en %.1f s (media %.1f valores/día)", time.time() - t0, out["avg"] or 0)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("Luk: control de calidad no calculado (%s)", exc)
        return None


KEEP = ("date", "close", "high_today", "low_today", "adr", "setup", "leader", "why", "setup_why", "anchor",
        "anchor_date", "anchor_since", "avwap", "ema9", "ema21", "ema50", "ema150", "e9up", "e21up", "dist52", "ep60",
        "high20", "high_date", "days", "leg", "leg_lo", "pull_lo", "depth", "depth_adr", "retrace", "support",
        "support_value", "dist_adr", "touch", "zone", "recovery", "vol_ratio", "inside", "nr7", "wide_day",
        "base_hi", "base_range_adr", "theme_n", "score", "base", "mult", "flags", "parts", "entry", "stop", "stop_min",
        "stop_pct", "size_pct", "r3", "r5", "level", "trigger", "ep_today", "gap", "vol_x")


def _slim(a: dict) -> dict:
    return {k: a.get(k) for k in KEEP if k in a}


# ---------------------------------------------------------------- kit para el directo (docs/data/live.json)
def _sig(x, d: int = 6):
    """Número con d cifras significativas (None si no es finito)."""
    if x is None or not np.isfinite(x):
        return None
    return float(f"{float(x):.{d}g}")


def _tail(arr, s: int, k: int = 5) -> list:
    return [_sig(arr[i]) if i >= 0 else None for i in range(s - k + 1, s + 1)]


def bar_kit(P: dict, s: int, n: int = 120, rnd: bool = True) -> dict:
    """Últimas n velas y colas de las EMA para recalcular el análisis en el navegador con la vela de hoy."""
    a = max(0, s - n + 1)
    f = _sig if rnd else (lambda x: float(x) if np.isfinite(x) else None)
    return {"t": P["dates"][a:s + 1], **{k: [f(x) for x in P[k][a:s + 1]] for k in ("o", "h", "l", "c")},
            "v": [int(x) for x in P["v"][a:s + 1]],
            **{f"e{k}": (_tail(P[f"e{k}"], s) if rnd else [f(x) for x in P[f"e{k}"][s - 4:s + 1]]) for k in (9, 21, 50, 150)},
            "hi252": f(P["hi252"][s])}


def health_kit(P: dict, s: int, q: dict) -> dict:
    """Lo necesario para el estado sano/dañado con la vela de hoy: colas de EMA 9/21, ADR y huecos de 4 sesiones."""
    gd = any(i >= 21 and not np.isnan(P["adr"][i - 1]) and P["gap"][i] <= -P["adr"][i - 1]
             for i in range(s - q["gap_days"] + 2, s + 1))
    return {"c": _sig(P["c"][s]), "adr": _sig(P["adr"][s]), "gd": bool(gd), "status": luk.health(P, s, q),
            **{f"e{k}": _tail(P[f"e{k}"], s) for k in (9, 21, 50, 150)}}


def live_kit(st: dict, prices: dict, fin: dict, session: str, view_by: dict | None = None) -> dict:
    """Datos para recalcular en el navegador, con la vela de hoy: setups, termómetro, ETF y EP."""
    q = st["cfg"]
    leaders, health, eps = {}, {}, {}
    fin_by = {x["sym"]: x for x in fin["setups"] + fin["l3"]}
    for sym in st["leaders"]:
        P = st["prepared"].get(sym)
        if P is None:
            continue
        u = st["uni"][sym]
        r = u["row"]
        v = (view_by or {}).get(sym) or {}
        leaders[sym] = {**bar_kit(P, P["n"] - 1), "rs": st["rs"].get(sym), "group": r.get("group"),
                        "group_name": v.get("group_name") or (fin_by.get(sym) or {}).get("group_name"),
                        "name": v.get("name") or r["info"].get("name") or sym, "mcap": u["mcap"], "uflags": u["flags"],
                        "next_earnings": v.get("next_earnings"),
                        "earn_known": bool(v.get("next_earnings")) or v.get("next_earnings_est") is not None}
    for sym in st["regime"]["counts"].get("all_syms", []):
        P = st["prepared"].get(sym)
        if P is not None:
            health[sym] = health_kit(P, P["n"] - 1, q)
    ctx = {}
    for etf in CONTEXT_ETFS:
        if etf in prices:
            P = luk.prepare(prices[etf], q)
            if P:
                ctx[etf] = health_kit(P, P["n"] - 1, q)
    for sym, u in st["uni"].items():
        if sym in leaders:
            continue
        df = prices[sym]
        if len(df) < 60:
            continue
        v = df["Volume"].fillna(0).to_numpy(float)
        h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
        eps[sym] = [_sig(df["Close"].iloc[-1]), _sig(float(np.mean(v[-50:]))), _sig(float(np.mean(h[-20:] / l[-20:]) - 1)),
                    u["row"]["info"].get("name") or sym]
    years = {int(session[:4]), int(session[:4]) + 1}
    from . import calendar_us
    holidays = sorted(d.isoformat() for y in years for d in calendar_us.holidays(y))
    return {"session": session, "cfg": {k: q[k] for k in luk.DEFAULTS if isinstance(q[k], (int, float, bool))},
            "holidays": holidays, "leaders": leaders, "health": health, "ctx": ctx, "eps": eps}
