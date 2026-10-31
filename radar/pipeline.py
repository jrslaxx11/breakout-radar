"""Orquestación diaria: descarga, cálculo de las fases 1-7 y escritura del JSON del dashboard."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from . import breakouts as bo
from . import fundamentals, history, qullamaggie as qm, regime, stars, themes
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
    stale: dict = {}
    if prices is None:
        from .prices import (complete_recent, download, drop_partial_bars, expected_session, fetch_quotes,
                             last_dates, patch_from_quotes)
        prices = download(list(universe) + etf_syms + idx_syms + bench_syms + fx_syms,
                          S["run"]["history_days"], S["run"]["download_chunk"], S["run"]["download_pause_s"])
        mc = S.get("market_close")
        if mc:
            try:  # la serie diaria de Yahoo trae el cierre del día con horas de retraso
                now_utc = datetime.now(timezone.utc)
                behind = [s for s, df in prices.items() if not s.endswith("=X") and df is not None and len(df)
                          and df.index[-1].date() < expected_session(s, mc, now_utc)]
                quotes = fetch_quotes(behind)
                patched = patch_from_quotes(prices, quotes, mc)
                log.info("última sesión: %d valores sin ella en la serie diaria, %d cotizaciones, %d completados",
                         len(behind), len(quotes), len(patched))
            except Exception as exc:  # noqa: BLE001
                log.warning("sin cotizaciones de cierre: %s", exc)
            dropped = drop_partial_bars(prices, mc)
            if dropped:
                log.info("barras parciales descartadas: %d", len(dropped))
            stale = complete_recent(prices, mc)
            log.info("última barra por mercado: %s", last_dates(prices, mc))

    ref = prices.get("^GSPC")
    session = ref.index[-1].strftime("%Y-%m-%d") if ref is not None and len(ref) else today.isoformat()
    prev = history.previous_snapshot(session)
    if not force and history.HISTORY_DIR.joinpath(f"{session}.json").exists():
        log.info("La sesión %s ya está procesada; nada que hacer.", session)
        if write:  # el flujo no vuelve a publicar la web: se queda la versión anterior
            DOCS_DATA.mkdir(parents=True, exist_ok=True)
            (DOCS_DATA / ".skipped").write_text(session)
        return {"skipped": True, "session": session}

    fx = _fx_factors(prices, S["fx"])
    bench = {}
    for b in bench_syms:
        m = compute(b, prices.get(b), w) if prices.get(b) is not None else None
        bench[b] = {"r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m} if m else {}

    ndx = prices.get("^NDX")
    qm_market = qm.market_filter(compute("^NDX", ndx, w) if ndx is not None else None)

    # ---------- métricas por valor ----------
    dups = cfg.duplicates()
    excluded = cfg.overrides.get("exclude") or {}
    rows: dict[str, dict] = {}
    for sym, info in universe.items():
        if sym in stale:
            continue  # sin la última sesión: no se clasifica con datos de un día antes
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
    qcfg = {**qm.DEFAULTS, **(S.get("qullamaggie") or {})}
    perf_cut = qm.perf_cutoffs([r["m"] for r in liquid], qcfg["top_pct"])

    # ---------- perfiles y temáticas ----------
    need_prof = [r["sym"] for r in sorted(liquid, key=lambda x: -x["rsc"]) if not r["info"].get("gics_sub")]
    prof = (profiles_fn or fundamentals.profiles)(need_prof, S["run"]["max_profile_fetch"])
    lookup = themes.build_lookup(theme_defs)
    for r in rows.values():
        r["profile"] = prof.get(r["sym"], {})
        r["theme"] = themes.assign(r["sym"], r["info"], r["profile"], lookup)

    spy = bench.get("^GSPC", {})
    etf_cache = {e: themes.etf_stats(prices, e, spy, w) for e in etf_syms}
    theme_stats, theme_etfs = {}, {}
    for key, t in theme_defs.items():
        members = [r for r in liquid if r["theme"] == key and not r["dup"]]
        if len(members) < 3:
            continue
        theme_etfs[key] = [etf_cache.get(e) for e in t.get("etfs") or [] if etf_cache.get(e)]
        theme_stats[key] = themes.stats(members, theme_etfs[key])
    ranks = themes.rs_ranks(theme_stats)
    weights = {**themes.DEFAULT_WEIGHTS, **(S.get("theme_score") or {})}
    theme_rows = []
    for key, st in theme_stats.items():
        theme_rows.append({"key": key, "name": theme_defs[key]["name"], **st, "rs_rank": ranks[key],
                           "score": themes.score(st, ranks[key], weights),
                           "status": themes.status(st), "etfs": theme_etfs[key]})
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
                "qm": qm.evaluate(m, state, qm_market, perf_cut, qcfg),
                "stars": stars.rate(m, theme_hot=True),
                "s10": m.s10, "adr_pct": m.adr_pct, **_level_fields(m),
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

    # ---------- vista completa para el buscador ----------
    search_view = []
    for sym, r in rows.items():
        mine = bool(r["info"].get("mine"))
        liq = (r["mdv_usd"] or 0) >= flt["min_mdv_usd"] and (r["price_usd"] or 0) >= flt["min_price_usd"]
        if not (liq or mine) or (r["dup"] and not mine):
            continue
        if sym in candidates:
            search_view.append(candidates[sym])
            continue
        m = r["m"]
        ev = evaluate(r, None)
        rk_label, rk_pts = bo.risk(m, ev["inv"], None, False, r["mdv_usd"] or 0, S["risk"])
        conf, inval = bo.conditions(m, ev["state"], ev["inv"])
        search_view.append({
            "sym": sym, "theme": r["theme"], "name": r["info"].get("name") or r["profile"].get("name") or sym,
            "exchange": "", "country": r["profile"].get("country") or "", "currency": r["cur"], "date": m.date,
            "close": m.C, "d1": m.d1, "state": ev["state"], "why": ev["why"], "excluded": "",
            "score": ev["score"]["total"], "components": ev["score"], "pivot": m.P, "pivot_date": m.piv_date,
            "dist": m.C / m.P - 1, "base_len": m.blen, "depth": m.depth, "inv": ev["inv"],
            "inv_pct": (ev["inv"] / m.C - 1) if ev["inv"] else None,
            "inv_atr": ((m.C - ev["inv"]) / m.atr) if ev["inv"] else None,
            "atr": m.atr, "atr_pct": m.atr_pct, "vol": m.vol, "v20": m.v20, "rvol": m.rvol, "vdry": m.vdry,
            "rs_pct": r.get("rs_pct"), "r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m, "dhi": m.dhi, "hi52": m.hi52,
            "s10": m.s10, "s20": m.s20, "s50": m.s50, "s200": m.s200, "adr_pct": m.adr_pct,
            "mdv_usd": r["mdv_usd"], "catalyst": "", "risk": rk_label, "risk_points": rk_pts,
            "confirm": conf, "invalidate": inval, "mine": mine, "liquid": liq,
            "qm": qm.evaluate(m, ev["state"], qm_market, perf_cut, qcfg),
            "stars": stars.rate(m, theme_hot=r["theme"] in selected), **_level_fields(m),
        })
    for c in search_view:
        if c["sym"] in candidates:
            c["mine"] = bool(rows[c["sym"]]["info"].get("mine"))
            c["liquid"] = True

    # ---------- escáner Qullamaggie: todo el universo líquido, solo rupturas ----------
    order = {bo.CONFIRMED: 0, bo.EARLY: 1, bo.RETEST: 2, bo.PRE: 3}
    qm_setups = []
    for c in search_view:
        q = c.get("qm") or {}
        if not c.get("liquid") or c.get("excluded") or q.get("verdict") == "No cumple" or c["state"] not in order:
            continue
        fails = [k["label"] for k in q.get("checks", []) if k["ok"] is False]
        st = c.get("stars") or {}
        qm_setups.append({
            "sym": c["sym"], "name": c["name"], "theme": c.get("theme"), "state": c["state"], "why": c["why"],
            "date": c["date"], "close": c["close"], "currency": c["currency"], "pivot": c["pivot"], "dist": c["dist"],
            "inv": c["inv"], "v20": c["v20"], "peak": c["peak"], "level_kind": c["level_kind"],
            "adr_pct": c["adr_pct"], "prior_move": c["prior_move"], "base_len": c["base_len"],
            "score": c["score"], "presented": bool(c.get("presented")), "fails": fails,
            "qm": {"verdict": q["verdict"], "trigger": q["trigger"], "stop_max": q["stop_max"]},
            "stars": st.get("stars"), "chart_stars": st.get("chart_stars"), "star_points": st.get("points"),
            "theme_bonus": bool(st.get("theme_bonus")), "hot_theme": c.get("theme") in selected,
        })
    # Primero las de más estrellas; a igualdad, las más avanzadas y las más cerca del nivel.
    qm_setups.sort(key=lambda x: (-(x["stars"] or 0), order[x["state"]], -x["dist"]))

    # ---------- acciones líderes de cada temática: mayor fuerza relativa compuesta ----------
    view_by = {c["sym"]: c for c in search_view}
    n_top = sel_cfg.get("leaders_per_theme", 10)
    for t in theme_rows:
        mem = sorted((r for r in liquid if r["theme"] == t["key"] and not r["dup"]), key=lambda r: -r["rsc"])
        t["top"] = []
        for r in mem[:n_top]:
            m, v = r["m"], view_by.get(r["sym"]) or {}
            t["top"].append({
                "sym": r["sym"], "name": v.get("name") or r["sym"], "currency": r["cur"], "close": m.C,
                "rs_pct": r.get("rs_pct"), "r1m": m.r1m, "r3m": m.r3m, "r6m": m.r6m, "dhi": m.dhi,
                "above50": bool(m.s50 and m.C > m.s50), "state": v.get("state"), "score": v.get("score"),
                "watch": bool(v.get("presented")),
            })

    coverage = {
        "universe": len(universe), "with_data": len(rows), "liquid": len(liquid),
        "by_source": {k: sum(1 for r in rows.values() if r["info"].get("source") == k)
                      for k in ("SPX", "MID", "SML", "INTL", "DISC")},
        "markets": sorted({cfg.suffix(s) or "US" for s in rows}),
        "missing_prices": len(universe) - len(rows) - len([s for s in stale if s in universe]),
        "stale": len([s for s in stale if s in universe]),
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
                  "pending": pending_list, "eliminated": eliminated, "qm_setups": qm_setups},
        "qm_market": qm_market,
        "qm_const": qm.constants(),
        "stars_const": stars.constants(),
        "theme_weights": weights,
        "calendar": calendar,
        "web": {"worker_url": (S.get("web") or {}).get("worker_url") or ""},
        # Contexto para evaluar en el navegador cualquier ticker con los mismos umbrales (docs/engine.js).
        "engine": {
            "settings": {k: S[k] for k in ("windows", "breakout", "filters", "risk", "benchmarks", "currency_by_suffix")},
            "benchmarks": bench, "fx": fx, "qm_market": qm_market, "perf_cut": perf_cut, "qullamaggie": qcfg,
            "rs_dist": [round(r["rsc"], 6) for r in sorted(liquid, key=lambda x: x["rsc"])],
        },
    }
    if write:
        DOCS_DATA.mkdir(parents=True, exist_ok=True)
        # Ficha por valor (puntuaciones + velas) e índice del buscador; se regeneran en cada ejecución
        # y no se versionan (solo viajan en la web publicada).
        cdir = DOCS_DATA / "c"
        cdir.mkdir(parents=True, exist_ok=True)
        for old in cdir.glob("*.json"):
            old.unlink()
        candles = _chart_data(prices, [c["sym"] for c in search_view], bars=S["run"].get("chart_bars", 330))
        for c in search_view:
            body = {"rec": _slim(c), "k": candles.get(c["sym"])}
            (cdir / f"{safe_name(c['sym'])}.json").write_text(
                json.dumps(_clean(body), ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_json_default))
        index = [[c["sym"], c.get("name") or "", c.get("theme") or "", c["state"], round(c["score"], 1)] for c in search_view]
        (DOCS_DATA / "universe.json").write_text(json.dumps({"session": session, "rows": index}, ensure_ascii=False,
                                                            separators=(",", ":")))
        (DOCS_DATA / "latest.json").write_text(json.dumps(_clean(out), ensure_ascii=False, allow_nan=False,
                                                          default=_json_default))
        snap = {"session": session,
                "regime": {"label": reg["label"], "score": reg["score"],
                           "p50_spx": (reg["breadth"].get("SPX", {}).get("now") or {}).get("p50")},
                "themes": {t["key"]: round(t["score"]["total"], 1) for t in theme_rows},
                "watchlist": {c["sym"]: {"score": round(c["score"], 2), "state": c["state"],
                                         "theme": c["theme"], "rs_pct": round(c["rs_pct"] or 0, 4)} for c in pres}}
        history.write_snapshot(session, _clean(snap))
    out["search_view"] = search_view  # solo para quien llama (pruebas); no va en latest.json
    return out


def _level_fields(m) -> dict:
    """Consolidación y nivel de ruptura para el dashboard."""
    return {"peak": m.peak, "level_kind": m.level_kind, "line": m.line, "touch_date": m.touch_date,
            "retrace": m.retrace, "tight_ratio": m.tight_ratio, "prior_move": m.prior_move}


def safe_name(sym: str) -> str:
    """Nombre de archivo seguro para un ticker (mismo criterio que el dashboard)."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in sym)


def _slim(o, sig: int = 5):
    """Redondea los decimales para que el archivo del buscador pese menos."""
    import math

    if isinstance(o, dict):
        return {k: _slim(v, sig) for k, v in o.items() if v is not None and v != ""}
    if isinstance(o, list):
        return [_slim(v, sig) for v in o]
    if isinstance(o, float) and math.isfinite(o) and o != 0:
        return round(o, max(0, sig - 1 - int(math.floor(math.log10(abs(o))))))
    return o


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
