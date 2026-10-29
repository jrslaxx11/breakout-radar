"""Orquestación diaria: descarga, cálculo de las fases 1-7 y escritura del JSON del dashboard."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from . import breakouts as bo
from . import fundamentals, history, regime, themes
from .config import DOCS_DATA, Config
from .metrics import compute, rel, rs_composite

log = logging.getLogger(__name__)
VERSION = "1.0.0"


def _fx_factors(prices: dict, fxcfg: dict) -> dict[str, float]:
    out = {"USD": 1.0}
    for cur, spec in fxcfg.items():
        df = prices.get(spec["pair"])
        if df is None or not len(df):
            continue
        px = float(df["Close"].iloc[-1])
        f = 1 / px if spec.get("inverse") else px
        out[cur] = f * spec.get("scale", 1)
    return out


def _stock_catalyst(sym: str, react: dict | None, has_earn_data: bool, overrides: dict,
                    today: date) -> tuple[float | None, str, str]:
    """(puntos 0-5 o None si no hay datos, texto, fuente)."""
    man = (overrides.get("stock_catalysts") or {}).get(sym)
    if man:
        try:
            d = date.fromisoformat(str(man["date"]))
            if (today - d).days <= overrides.get("expires_days", 21):
                return float(man["points"]), man.get("note", ""), man.get("source", "")
        except (KeyError, ValueError):
            pass
    if react and not react.get("pending") and react.get("sessions_ago") is not None:
        txt = f"Resultados {react['day']}: {react['react'] * 100:+.1f}%".replace(".", ",")
        if react["sessions_ago"] <= 15 and react["react"] > 0.02 and react["since"] > -0.02:
            return 4.0, txt + " (reacción positiva mantenida)", ""
        return 0.0, txt, ""
    if has_earn_data:
        return 0.0, "", ""
    return None, "sin datos de resultados", ""


def run(cfg: Config | None = None, *, universe: dict | None = None, prices: dict | None = None,
        details_fn=None, profiles_fn=None, today: date | None = None, write: bool = True,
        force: bool = False) -> dict:
    cfg = cfg or Config.load()
    S = cfg.settings
    w, bcfg, flt = S["windows"], S["breakout"], S["filters"]
    tz = ZoneInfo(S["run"].get("timezone", "Europe/Madrid"))
    now_local = datetime.now(tz)
    today = today or now_local.date()

    # ---------- universo y precios ----------
    if universe is None:
        from .universe import build_universe
        universe = build_universe(cfg)
    theme_defs = cfg.theme_defs
    etf_syms = sorted({e for t in theme_defs.values() for e in (t.get("etfs") or [])}
                      | set(cfg.themes.get("reference_etfs", [])))
    idx_syms = [i["sym"] for i in S["regime"]["indices"]] + S["regime"]["volatility"]
    bench_syms = sorted({S["benchmarks"]["default"], *S["benchmarks"]["by_suffix"].values()})
    fx_syms = sorted({v["pair"] for v in S["fx"].values()})
    if prices is None:
        from .prices import download
        prices = download(list(universe) + etf_syms + idx_syms + bench_syms + fx_syms,
                          S["run"]["history_days"], S["run"]["download_chunk"], S["run"]["download_pause_s"])

    ref = prices.get("^GSPC")
    session = ref.index[-1].strftime("%Y-%m-%d") if ref is not None and len(ref) else today.isoformat()
    prev = history.previous_snapshot(session)
    if not force and history.HISTORY_DIR.joinpath(f"{session}.json").exists():
        log.info("La sesión %s ya está procesada; nada que hacer.", session)
        latest = DOCS_DATA / "latest.json"
        if write and latest.exists():  # las velas no se versionan: se regeneran para la publicación
            pres = json.loads(latest.read_text()).get("lists", {}).get("presented", [])
            (DOCS_DATA / "charts.json").write_text(json.dumps(_clean(_chart_data(prices, pres)),
                                                              separators=(",", ":"), allow_nan=False))
        return {"skipped": True, "session": session}

    fx = _fx_factors(prices, S["fx"])
    bench = {}
    for b in bench_syms:
        m = compute(b, prices.get(b), w) if prices.get(b) is not None else None
        bench[b] = {"r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m} if m else {}

    # ---------- métricas por valor ----------
    dups = cfg.duplicates()
    excluded = cfg.overrides.get("exclude") or {}
    rows: dict[str, dict] = {}
    for sym, info in universe.items():
        df = prices.get(sym)
        m = compute(sym, df, w) if df is not None else None
        if m is None:
            continue
        cur = cfg.currency(sym)
        f = fx.get(cur)
        b = bench.get(cfg.benchmark(sym), {})
        rs1, rs3, rs6 = rel(m.r1m, b.get("r1m")), rel(m.r3m, b.get("r3m")), rel(m.r6m, b.get("r6m"))
        rows[sym] = {
            "sym": sym, "m": m, "info": info, "cur": cur, "fx": f,
            "mdv_usd": m.mdv * f if f else None, "price_usd": m.C * f if f else None,
            "rs1": rs1, "rs3": rs3, "rs6": rs6, "rsc": rs_composite(rs1, rs3, rs6),
            "unbiased": info.get("unbiased", False), "dup": info.get("duplicate_of") or dups.get(sym),
        }
    liquid = [r for r in rows.values()
              if (r["mdv_usd"] or 0) >= flt["min_mdv_usd"] and (r["price_usd"] or 0) >= flt["min_price_usd"]]
    for i, r in enumerate(sorted(liquid, key=lambda x: x["rsc"])):
        r["rs_pct"] = (i + 1) / len(liquid)

    # ---------- perfiles y temáticas ----------
    need_prof = [r["sym"] for r in sorted(liquid, key=lambda x: -x["rsc"]) if not r["info"].get("gics_sub")]
    prof = (profiles_fn or fundamentals.profiles)(need_prof, S["run"]["max_profile_fetch"])
    lookup = themes.build_lookup(theme_defs)
    for r in rows.values():
        r["profile"] = prof.get(r["sym"], {})
        r["theme"] = themes.assign(r["sym"], r["info"], r["profile"], lookup)

    spy = bench.get("^GSPC", {})
    etf_cache = {e: themes.etf_stats(prices, e, spy, w) for e in etf_syms}
    theme_rows = []
    for key, t in theme_defs.items():
        members = [r for r in liquid if r["theme"] == key and not r["dup"]]
        if len(members) < 3:
            continue
        etfs = [etf_cache.get(e) for e in t.get("etfs") or [] if etf_cache.get(e)]
        st = themes.stats(members, etfs)
        cat = themes.theme_catalyst(key, cfg.overrides, today) or themes.catalyst_auto(st)
        sc = themes.score(st, cat)
        theme_rows.append({"key": key, "name": t["name"], **st, "score": sc, "catalyst": cat,
                           "status": themes.status(st), "etfs": etfs})
    theme_rows.sort(key=lambda x: -x["score"]["total"])
    sel_cfg = S["selection"]
    cut = theme_rows[min(sel_cfg["top_themes"], len(theme_rows)) - 1]["score"]["total"] if theme_rows else 0
    natural = [t["key"] for t in theme_rows
               if t["score"]["total"] >= cut - sel_cfg["tie_points"]][: sel_cfg["top_themes"] + 3]
    selected = list(natural)
    for k in sel_cfg.get("force_themes") or []:
        if k not in selected and any(t["key"] == k for t in theme_rows):
            selected.append(k)
    for t in theme_rows:
        t["selected"] = t["key"] in selected
        t["forced"] = t["key"] in selected and t["key"] not in natural

    # ---------- acciones: clasificación y puntuación ----------
    def evaluate(r: dict, catalyst: float | None) -> dict:
        m = r["m"]
        c = bo.classify(m, r["mdv_usd"], r["price_usd"], bcfg, flt)
        state, why = c.state, c.why
        if r["sym"] in excluded:
            state, why = bo.DISCARDED, excluded[r["sym"]].get("reason", "exclusión manual")
        inv = bo.invalidation(m, state)
        sc = bo.score(m, state, r.get("rs_pct", 0), r["mdv_usd"] or 0, catalyst)
        return {"state": state, "why": why, "inv": inv, "score": sc}

    examined: dict[str, list[dict]] = {}
    detail_syms: list[str] = []
    for key in selected:
        pool = [r for r in liquid if r["theme"] == key and not r["dup"] and r.get("rs_pct", 0) >= sel_cfg["min_rs_pct"]]
        for r in pool:
            r["pre"] = evaluate(r, 0.0)
        pool.sort(key=lambda r: -r["pre"]["score"]["total"])
        examined[key] = pool[: sel_cfg["examine_per_theme"]]
        detail_syms += [r["sym"] for r in examined[key]]

    det = (details_fn or fundamentals.details)(list(dict.fromkeys(detail_syms)))
    candidates: dict[str, dict] = {}
    for key, pool in examined.items():
        for r in pool:
            m, sym = r["m"], r["sym"]
            d = det.get(sym, {})
            react = fundamentals.earnings_reaction(prices[sym], d.get("last_earnings"), d.get("tz") or "America/New_York")
            pending = bool(react and react.get("pending"))
            has_e = bool(d.get("last_earnings") or d.get("next_earnings"))
            cat, cat_txt, cat_src = _stock_catalyst(sym, react, has_e, cfg.overrides, today)
            ev = evaluate(r, cat)
            state, why = ev["state"], ev["why"]
            excl_reason = ""
            if pending:
                excl_reason = "resultados publicados tras el último cierre: pendiente de la reacción"
            mc_usd = d["mcap"] * fx.get(d.get("currency") or r["cur"], r["fx"] or 1) if d.get("mcap") else None
            if d.get("currency") == "GBp" and mc_usd:
                mc_usd *= 100  # Yahoo da la capitalización en libras aunque el precio esté en peniques
            if mc_usd is not None and mc_usd < flt["min_mcap_usd"]:
                excl_reason = excl_reason or "capitalización < 500 M USD"
            next_days = fundamentals.days_until(d.get("next_earnings"), today)
            rk_label, rk_pts = bo.risk(m, ev["inv"], next_days, pending, r["mdv_usd"] or 0, S["risk"])
            conf, inval = bo.conditions(m, state, ev["inv"])
            candidates[sym] = {
                "sym": sym, "theme": key, "name": d.get("name") or r["info"].get("name") or r["profile"].get("name") or sym,
                "exchange": d.get("exchange") or "", "country": d.get("country") or r["profile"].get("country") or "",
                "currency": r["cur"], "date": m.date, "close": m.C, "d1": m.d1,
                "state": state, "why": why, "excluded": excl_reason,
                "score": ev["score"]["total"], "components": ev["score"],
                "pivot": m.P, "pivot_date": m.piv_date, "dist": m.C / m.P - 1, "base_len": m.blen, "depth": m.depth,
                "inv": ev["inv"], "inv_pct": (ev["inv"] / m.C - 1) if ev["inv"] else None,
                "inv_atr": ((m.C - ev["inv"]) / m.atr) if ev["inv"] else None,
                "atr": m.atr, "atr_pct": m.atr_pct, "vol": m.vol, "v20": m.v20, "rvol": m.rvol, "vdry": m.vdry,
                "rs_pct": r.get("rs_pct"), "r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m,
                "rs1": r["rs1"], "rs3": r["rs3"], "rs6": r["rs6"], "dhi": m.dhi, "hi52": m.hi52,
                "s20": m.s20, "s50": m.s50, "s200": m.s200,
                "mcap_usd": mc_usd, "mdv_usd": r["mdv_usd"],
                "next_earnings": d.get("next_earnings"), "next_earnings_est": d.get("next_earnings_est"),
                "last_earnings": react["day"] if react else None, "earnings_pending": pending,
                "catalyst": cat_txt, "catalyst_source": cat_src,
                "risk": rk_label, "risk_points": rk_pts, "confirm": conf, "invalidate": inval,
            }

    # ---------- listas ----------
    show = sel_cfg["show_per_theme"]
    presented: list[str] = []
    for key in selected:
        ok = [c for c in candidates.values() if c["theme"] == key and not c["excluded"] and c["state"] in bo.ACTIONABLE]
        ok.sort(key=lambda c: -c["score"])
        presented += [c["sym"] for c in ok[:show]]
    for s in presented:
        candidates[s]["presented"] = True
    pres = [candidates[s] for s in presented]
    global_top = [c["sym"] for c in sorted(pres, key=lambda c: -c["score"])[: sel_cfg["global_top"]]]
    for i, s in enumerate(global_top):
        candidates[s]["rank_global"] = i + 1

    priority, seen_t = [], set()
    for c in sorted(pres, key=lambda c: -c["score"]):
        nd = fundamentals.days_until(c["next_earnings"], today)
        if c["risk"] == "Alto" or (nd is not None and 0 <= nd <= 7) or c["theme"] in seen_t:
            continue
        priority.append(c["sym"])
        seen_t.add(c["theme"])
        if len(priority) >= sel_cfg["priority"]:
            break
    for i, s in enumerate(priority):
        candidates[s]["priority"] = i + 1

    by_state = {st: [c["sym"] for c in sorted(pres, key=lambda c: -c["score"]) if c["state"] == st]
                for st in bo.ACTIONABLE}
    others = [{"sym": c["sym"], "theme": c["theme"], "state": c["state"],
               "reason": c["excluded"] or c["why"] or c["state"].lower(), "score": c["score"]}
              for c in candidates.values() if not c.get("presented")]

    # Rupturas confirmadas fuera de las temáticas seleccionadas (RS ≥ 80%).
    outside = []
    for r in liquid:
        if r.get("rs_pct", 0) < 0.8 or r["dup"] or r["theme"] in selected or (r["mdv_usd"] or 0) < 10e6:
            continue
        c = bo.classify(r["m"], r["mdv_usd"], r["price_usd"], bcfg, flt)
        if c.state == bo.CONFIRMED:
            outside.append({"sym": r["sym"], "theme": r["theme"], "rs_pct": r["rs_pct"],
                            "name": r["info"].get("name") or r["profile"].get("name") or "",
                            "dist": r["m"].C / r["m"].P - 1, "rvol": r["m"].rvol, "why": c.why})
    outside.sort(key=lambda x: -x["rs_pct"])

    calendar = sorted(({"date": c["next_earnings"], "sym": c["sym"], "est": c["next_earnings_est"]}
                       for c in pres if c["next_earnings"]
                       and 0 <= (fundamentals.days_until(c["next_earnings"], today) or 99) <= 45),
                      key=lambda x: (x["date"], x["sym"]))
    pending_list = [c["sym"] for c in candidates.values() if c["earnings_pending"]]

    # ---------- histórico ----------
    for c in pres:
        c["daily_status"], c["score_prev"] = history.daily_status(c["sym"], c, prev)
    analysed = {s: {"state": c["state"], "why": c["why"], "theme": c["theme"]} for s, c in candidates.items()}
    for s, r in rows.items():
        if s not in analysed and r.get("theme"):
            st = bo.classify(r["m"], r["mdv_usd"], r["price_usd"], bcfg, flt)
            analysed[s] = {"state": st.state, "why": st.why, "theme": r["theme"]}
    watch = {c["sym"]: c for c in pres}
    watch["__themes__"] = selected
    eliminated = history.removed(watch, prev, analysed)

    # ---------- régimen ----------
    sp_groups = {k: [s for s, i in universe.items() if i.get("source") == k] for k in ("SPX", "MID", "SML")}
    reg = regime.regime(prices, S, sp_groups)

    coverage = {
        "universe": len(universe), "with_data": len(rows), "liquid": len(liquid),
        "by_source": {k: sum(1 for r in rows.values() if r["info"].get("source") == k)
                      for k in ("SPX", "MID", "SML", "INTL", "DISC")},
        "markets": sorted({cfg.suffix(s) or "US" for s in rows}),
        "missing_prices": len(universe) - len(rows),
    }
    out = {
        "meta": {"version": VERSION, "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "generated_local": now_local.isoformat(timespec="minutes"), "session": session,
                 "previous_session": prev["session"] if prev else None, "coverage": coverage,
                 "price_source": "Yahoo Finance (yfinance), cierres diarios ajustados por splits"},
        "regime": reg,
        "themes": [{k: v for k, v in t.items() if k != "members"} for t in theme_rows],
        "selected_themes": selected,
        "candidates": sorted(candidates.values(), key=lambda c: -c["score"]),
        "lists": {"presented": presented, "global_top": global_top, "priority": priority,
                  "by_state": by_state, "others": others, "outside": outside[:15],
                  "pending": pending_list, "eliminated": eliminated},
        "calendar": calendar,
    }
    if write:
        DOCS_DATA.mkdir(parents=True, exist_ok=True)
        (DOCS_DATA / "charts.json").write_text(json.dumps(_clean(_chart_data(prices, presented)),
                                                          separators=(",", ":"), allow_nan=False))
        (DOCS_DATA / "latest.json").write_text(json.dumps(_clean(out), ensure_ascii=False, allow_nan=False,
                                                          default=_json_default))
        snap = {"session": session,
                "regime": {"label": reg["label"], "score": reg["score"],
                           "p50_spx": (reg["breadth"].get("SPX", {}).get("now") or {}).get("p50")},
                "themes": {t["key"]: round(t["score"]["total"], 1) for t in theme_rows},
                "watchlist": {c["sym"]: {"score": round(c["score"], 2), "state": c["state"],
                                         "theme": c["theme"], "rs_pct": round(c["rs_pct"] or 0, 4)} for c in pres}}
        history.write_snapshot(session, _clean(snap))
    return out


def _chart_data(prices: dict, syms: list[str], bars: int = 260) -> dict:
    """Velas diarias de las candidatas presentadas para el gráfico del dashboard."""
    out = {}
    for s in syms:
        df = prices.get(s)
        if df is None or not len(df):
            continue
        df = df.dropna(subset=["Close", "High", "Low"]).tail(bars)
        last = float(df["Close"].iloc[-1])
        dec = 2 if last >= 10 else 4
        r = lambda col: [round(float(x), dec) for x in df[col].fillna(df["Close"])]  # noqa: E731
        out[s] = {
            "t": [d.strftime("%Y-%m-%d") for d in df.index],
            "o": r("Open") if "Open" in df else r("Close"), "h": r("High"), "l": r("Low"), "c": r("Close"),
            "v": [int(x) for x in df["Volume"].fillna(0)] if "Volume" in df else [],
        }
    return out


def _clean(o):
    """NaN e infinitos no son JSON válido: se sustituyen por null."""
    import math

    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(type(o))
