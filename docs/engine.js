/* Radar de rupturas · motor en el navegador.
 * Réplica exacta de radar/metrics.py, radar/breakouts.py y radar/qullamaggie.py para evaluar
 * al momento cualquier ticker que no esté en el universo diario. Los parámetros llegan en
 * latest.json (engine_settings), así que ambos motores usan los mismos umbrales.
 * tests/test_js_parity.py comprueba que Python y JavaScript dan el mismo resultado. */
(function (root) {
  "use strict";

  const isNum = (x) => typeof x === "number" && isFinite(x);
  const sma = (a, n, end) => {
    if (end + 1 < n || end < 0) return null;
    let s = 0;
    for (let i = end - n + 1; i <= end; i++) s += a[i];
    return s / n;
  };
  const minR = (a, i, j) => { let m = Infinity; for (let k = i; k <= j; k++) m = Math.min(m, a[k]); return m; };
  const maxR = (a, i, j) => { let m = -Infinity; for (let k = i; k <= j; k++) m = Math.max(m, a[k]); return m; };
  // Mismo formato que Python: f"{x:,.2f}" con punto de miles y coma decimal.
  const fmtEs = (x, d) => {
    const [ip, dp] = Math.abs(x).toFixed(d).split(".");
    return (x < 0 ? "-" : "") + ip.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (dp ? "," + dp : "");
  };
  const pctEs = (x, d = 1) => (x * 100).toFixed(d).replace(".", ",") + "%";

  function compute(sym, k, w) {
    const c = [], h = [], l = [], o = [], v = [], t = [];
    for (let i = 0; i < k.c.length; i++) {
      if (!isNum(k.c[i]) || !isNum(k.h[i]) || !isNum(k.l[i])) continue;
      c.push(k.c[i]); h.push(k.h[i]); l.push(k.l[i]); o.push(isNum(k.o?.[i]) ? k.o[i] : NaN);
      v.push(isNum(k.v?.[i]) ? k.v[i] : 0); t.push(k.t[i]);
    }
    const n = c.length, e = n - 1;
    if (n < 130 || c[e] <= 0) return null;
    const ret = (kk) => (n > kk ? c[e] / c[e - kk] - 1 : null);
    const s20 = sma(c, 20, e), s50 = sma(c, 50, e), s150 = sma(c, 150, e), s200 = sma(c, 200, e);
    const s50p = sma(c, 50, e - 20), s150p = sma(c, 150, e - 20), s200p = sma(c, 200, e - 20);
    let trs = 0, cnt = 0;
    for (let i = Math.max(1, e - 13); i <= e; i++) {
      trs += Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])); cnt++;
    }
    const atr = trs / cnt;
    const lb = Math.min(252, n);
    const hi52 = maxR(h, n - lb, e), lo52 = minR(l, n - lb, e);
    const v20 = sma(v, 20, e - 1), v50 = sma(v, 50, e - 1), v10 = sma(v, 10, e);
    const dv = []; for (let i = Math.max(0, e - 19); i <= e; i++) dv.push(c[i] * v[i]);
    dv.sort((a, b) => a - b);
    const mdv = dv[Math.floor(dv.length / 2)];
    // Consolidación y nivel de ruptura (igual que radar/metrics.py: _base_at).
    const lookback = w.pivot_lookback ?? 60, baseMin = w.base_min ?? 5, cw = w.cross_window ?? 5, recentN = w.recent_highs ?? 3;
    let crossI = null, base = null;
    for (let d = Math.max(1, e - cw); d <= e; d++) {
      const b = baseAt(h, d, lookback, baseMin, recentN, true);
      if (b && c[d] > b.level) { crossI = d; base = b; break; }
    }
    if (!base) base = baseAt(h, e + 1, lookback, baseMin, recentN, false);
    const { ip, H, slope, jt, lineV } = base, P = base.level;
    const dLvl = crossI !== null ? crossI : e + 1;
    const baseEnd = crossI !== null ? crossI - 1 : e;
    const Lb = minR(l, ip, baseEnd);
    const loMove = minR(l, Math.max(0, ip - 63), ip);
    const kind = P > lineV + 1e-9 ? "rango" : (H - lineV > 0.02 * H ? "línea" : "máximo");
    const maxCloseSince = crossI !== null ? maxR(c, crossI, e) : null;
    let rvolCross = null;
    if (crossI !== null) { const bv = sma(v, 20, crossI - 1); rvolCross = bv ? v[crossI] / bv : null; }
    const hi10 = maxR(h, e - 9, e), lo10 = minR(l, e - 9, e), lo5 = minR(l, e - 4, e);
    const rng = h[e] - l[e];
    let adr = 0; for (let i = e - 19; i <= e; i++) adr += h[i] / l[i];
    const span = baseEnd - ip;
    let higherLows = null;
    if (span >= 6) { const mid = ip + Math.floor(span / 2); higherLows = minR(l, mid, baseEnd) > minR(l, ip, mid - 1); }
    const s10 = sma(c, 10, e);
    return {
      sym, date: t[e], n, C: c[e], d1: c[e] / c[e - 1] - 1,
      r1m: ret(w.r1m ?? 21), r3m: ret(w.r3m ?? 63), r6m: ret(w.r6m ?? 126), r12m: ret(w.r12m ?? 250),
      s20, s50, s150, s200,
      s50up: s50 && s50p ? s50 > s50p : null, s150up: s150 && s150p ? s150 > s150p : null,
      s200up: s200 && s200p ? s200 > s200p : null,
      atr, atr_pct: atr / c[e], hi52, lo52, dhi: c[e] / hi52 - 1,
      vol: v[e], v20, v50, rvol: v20 ? v[e] / v20 : null, vdry: v10 !== null && v50 ? v10 / v50 : null, mdv,
      P, piv_date: t[ip], blen: crossI !== null ? dLvl - ip : e - ip, depth: 1 - Lb / H,
      cross: crossI !== null ? e - crossI : null,
      any_closed_above: crossI !== null, max_close_since: maxCloseSince, rvol_cross: rvolCross,
      tight: (hi10 - lo10) / c[e], lo5, lo10, day_pos: rng > 0 ? (c[e] - l[e]) / rng : 0.5,
      gap: isNum(o[e]) ? o[e] / c[e - 1] - 1 : 0,
      high: h[e], low: l[e], s10, s10up: n > 20 ? s10 > sma(c, 10, e - 5) : null,
      s20up: s20 && n > 30 ? s20 > sma(c, 20, e - 5) : null,
      adr_pct: adr / 20 - 1, prior_move: H / loMove - 1, higher_lows: higherLows,
      peak: H, level_kind: kind, line_slope: slope, touch_date: jt !== ip ? t[jt] : null,
      line: [[t[ip], H], [dLvl <= e ? t[dLvl] : nextSession(t[e]), lineV]],
      retrace: H > loMove ? (H - Lb) / (H - loMove) : null, tight_ratio: tightRatio(h, l, ip, baseEnd),
    };
  }

  // Máximo de la base, tangente superior desde él y nivel a superar el día d (ver radar/metrics.py).
  function baseAt(h, d, lookback, baseMin, recentN, require) {
    const start = Math.max(0, d - lookback);
    if (d - 1 < start) return null;
    let ip = start;
    for (let i = start; i < d; i++) if (h[i] > h[ip]) ip = i;
    if (require && d - ip < baseMin) return null;
    const H = h[ip];
    let slope = 0, jt = ip;
    if (d - 1 > ip) {
      let best = -Infinity;
      for (let j = ip + 1; j < d; j++) { const sl = (h[j] - H) / (j - ip); if (sl > best) { best = sl; jt = j; } }
      slope = Math.min(best, 0);
    }
    const lineV = H + slope * (d - ip);
    const lo = Math.max(ip + 1, d - recentN);
    const recent = lo < d ? maxR(h, lo, d - 1) : lineV;
    return { ip, H, slope, jt, lineV, level: Math.max(lineV, recent) };
  }

  function tightRatio(h, l, ip, end) {
    const nb = end - ip;
    if (nb < 4) return null;
    const lateN = Math.min(5, Math.floor(nb / 2));
    const mean = (i0, i1) => { let s = 0; for (let i = i0; i <= i1; i++) s += h[i] / l[i] - 1; return s / (i1 - i0 + 1); };
    if (end - lateN < ip + 1) return null;
    const early = mean(ip + 1, end - lateN);
    if (early <= 0) return null;
    return mean(end - lateN + 1, end) / early;
  }

  function nextSession(iso) {
    const d = new Date(iso + "T00:00:00Z");
    do { d.setUTCDate(d.getUTCDate() + 1); } while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
    return d.toISOString().slice(0, 10);
  }

  const rel = (r, b) => (r === null || b === null || b === undefined ? null : (1 + r) / (1 + b) - 1);
  const rsComposite = (a, b, c6) => {
    const r6 = c6 !== null ? c6 : (b !== null ? b : 0);
    return (a || 0) * 0.2 + (b || 0) * 0.4 + r6 * 0.4;
  };

  function shortBase(c, m, cfg) {
    if (m.blen < cfg.pre_min_base) c.why = (c.why ? c.why + "; " : "") + `base corta (${m.blen} ses.)`;
    return c;
  }

  function classify(m, mdvUsd, priceUsd, cfg, flt) {
    if (mdvUsd === null || mdvUsd < flt.min_mdv_usd || (priceUsd || 0) < flt.min_price_usd)
      return { state: "DESCARTADA", why: "liquidez o precio insuficiente" };
    if (m.atr_pct < cfg.pinned_atr_pct && m.tight < 0.025) return { state: "DESCARTADA", why: "precio anclado (posible OPA)" };
    if (m.s50 && m.C < m.s50 && m.s50up === false) return { state: "DESCARTADA", why: "bajo SMA50 descendente" };
    const P = m.P, C = m.C;
    if (C > P) {
      const ext = C / P - 1;
      if (ext > cfg.extended_pct || (m.s20 && (C - m.s20) > cfg.extended_atr_over_sma20 * m.atr))
        return { state: "EXTENDIDA", why: `+${(ext * 100).toFixed(1).replace(".", ",")}% sobre el nivel de ruptura` };
      if (m.cross === 0) {
        if ((m.rvol || 0) >= cfg.rvol_confirm && m.day_pos >= 0.5) return shortBase({ state: "CONFIRMADA", why: "" }, m, cfg);
        const why = (m.rvol || 0) < cfg.rvol_confirm ? "volumen < 1,5x" : "cierre en la mitad baja del rango";
        return shortBase({ state: "TEMPRANA", why }, m, cfg);
      }
      if (m.max_close_since && m.max_close_since / P - 1 >= cfg.retest_band && ext <= cfg.retest_band)
        return { state: "RETEST", why: "vuelve al nivel de ruptura" };
      if ((m.rvol_cross || 0) >= cfg.rvol_confirm && ext <= 0.06)
        return shortBase({ state: "CONFIRMADA", why: `ruptura hace ${m.cross} ses.` }, m, cfg);
      const rc = m.rvol_cross ? m.rvol_cross.toFixed(1).replace(".", ",") : "?";
      return shortBase({ state: "TEMPRANA", why: `cruce hace ${m.cross} ses. con ${rc}x volumen` }, m, cfg);
    }
    const dist = P / C - 1;
    if (m.any_closed_above && C < P * (1 - cfg.failed_break_pct)) return { state: "DESCARTADA", why: "ruptura fallida" };
    if (m.any_closed_above) return { state: "RETEST", why: "perdió el nivel de ruptura tras cruzarlo" };
    const above50 = !!(m.s50 && C > m.s50);
    if (m.blen < cfg.flag_min_base) {
      if (m.s20 && (C - m.s20) > cfg.extended_atr_over_sma20 * m.atr) return { state: "EXTENDIDA", why: "en plena subida, sin consolidación" };
      if (above50) return { state: "EN BASE", why: `base en formación (${m.blen} ses.)` };
    }
    if (dist <= cfg.pre_dist && m.blen >= cfg.pre_min_base && m.depth <= cfg.pre_max_depth && above50) return { state: "PRE-BREAKOUT", why: "" };
    if (dist <= cfg.pre_dist && m.blen >= cfg.flag_min_base && m.depth <= cfg.flag_max_depth && above50)
      return { state: "PRE-BREAKOUT", why: `flag corto (${m.blen} ses.)` };
    if (dist <= cfg.base_max_dist && above50) return { state: "EN BASE", why: `${(dist * 100).toFixed(1).replace(".", ",")}% bajo el nivel de ruptura` };
    return { state: "DESCARTADA", why: !above50 ? "bajo SMA50" : `${(dist * 100).toFixed(0)}% bajo el nivel de ruptura` };
  }

  function invalidation(m, st) {
    if (st === "CONFIRMADA" || st === "TEMPRANA" || st === "RETEST") return Math.max(m.P - m.atr, Math.min(m.lo5, m.P * 0.97));
    if (st === "PRE-BREAKOUT" || st === "EN BASE") return (m.C - m.lo10) > 2.5 * m.atr ? m.lo5 : m.lo10;
    if (st === "EXTENDIDA") return m.s20;
    return null;
  }

  function score(m, st, rsPct, mdvUsd, catalyst) {
    const pRs = 25 * (rsPct || 0);
    const dep = m.depth <= 0.15 ? 8 : m.depth <= 0.25 ? 6 : m.depth <= 0.35 ? 3 : 0;
    const bl = m.blen >= 15 ? 4 : m.blen >= 10 ? 3 : 1;
    const tr = m.atr_pct ? m.tight / m.atr_pct : 99;
    const ti = tr <= 4.5 ? 5 : tr <= 6.5 ? 3 : 1;
    const vd = m.vdry !== null ? m.vdry : 1.2;
    const dry = vd <= 0.9 ? 3 : vd <= 1.1 ? 2 : 1;
    const hi = m.dhi >= -0.05 ? 5 : m.dhi >= -0.15 ? 3 : m.dhi >= -0.25 ? 1 : 0;
    const pBase = dep + bl + ti + dry + hi;
    const rvol = m.rvol || 0;
    let pBo;
    if (st === "CONFIRMADA" && m.cross) pBo = 15 + ((m.rvol_cross || 0) >= 2 ? 3 : 0);
    else pBo = { CONFIRMADA: 17 + (rvol >= 2 ? 3 : 0), TEMPRANA: 10 + (rvol >= 1.2 ? 2 : 0), RETEST: 12 + (rvol < 1 ? 2 : 0),
      "PRE-BREAKOUT": 7 + (vd < 0.9 ? 2 : 0) + ((m.P / m.C - 1) <= 0.02 ? 2 : 0), EXTENDIDA: 5, "EN BASE": 3, DESCARTADA: 0 }[st];
    const pTr = (m.s20 && m.C > m.s20 ? 3 : 0) + (m.s50 && m.C > m.s50 ? 3 : 0) + (m.s200 && m.s50 && m.s50 > m.s200 ? 3 : 0)
      + (m.s200up ? 3 : 0) + (m.s150up && m.s150 && m.C > m.s150 ? 3 : 0);
    let pLiq = mdvUsd >= 50e6 ? 10 : mdvUsd >= 20e6 ? 8 : mdvUsd >= 10e6 ? 6 : mdvUsd >= 5e6 ? 4 : 0;
    if (m.n < 200) pLiq -= 2;
    const parts = { rs: pRs, base: pBase, breakout: pBo, trend: pTr, liquidity: pLiq };
    const sum = pRs + pBase + pBo + pTr + pLiq;
    let total;
    if (catalyst === null || catalyst === undefined) { parts.catalyst = null; total = sum * 100 / 95; }
    else { parts.catalyst = catalyst; total = sum + catalyst; }
    parts.total = Math.round(total * 100) / 100;
    return parts;
  }

  function risk(m, inv, nextDays, pending, mdvUsd, rc) {
    let pts = m.atr_pct >= 0.07 ? 3 : m.atr_pct >= 0.05 ? 2 : m.atr_pct >= 0.03 ? 1 : 0;
    if (pending) pts += 3;
    else if (nextDays !== null && nextDays >= 0 && nextDays <= rc.earnings_near_days) pts += 2;
    else if (nextDays !== null && nextDays >= 0 && nextDays <= rc.earnings_mid_days) pts += 1;
    if (inv) {
      const invAtr = m.atr ? (m.C - inv) / m.atr : 0;
      if (invAtr > 2.5 || (m.C / inv - 1) > 0.10) pts += 1;
    }
    if (mdvUsd < 20e6) pts += 1;
    return [pts >= 4 ? "Alto" : pts >= 2 ? "Medio" : "Bajo", pts];
  }

  function conditions(m, st, inv) {
    const f = (x) => fmtEs(x, x >= 1000 ? 0 : 2);
    const v15 = 1.5 * (m.v20 || 0);
    const volTxt = v15 >= 1e5 ? `${(v15 / 1e6).toFixed(2).replace(".", ",")} M` : fmtEs(Math.round(v15), 0);
    const invTxt = inv ? `Cierre < ${f(inv)}` : "";
    if (st === "CONFIRMADA") return [`Cierres sostenidos > ${f(m.P)} con volumen ≥ media`, invTxt];
    if (st === "TEMPRANA") return [`Nuevo cierre > ${f(Math.max(m.P, m.C))} con ≥ ${volTxt} (1,5x)`, invTxt];
    if (st === "RETEST") return [m.C > m.P ? `Rebote desde ${f(m.P)} con volumen creciente` : `Recuperar y cerrar > ${f(m.P)}`, invTxt];
    if (st === "PRE-BREAKOUT" || st === "EN BASE") {
      return [`Cierre > ${f(m.P)}${m.level_kind === "línea" ? " (resistencia descendente)" : ""} con ≥ ${volTxt} (1,5x)`, invTxt];
    }
    if (st === "EXTENDIDA") return ["Esperar base nueva o retroceso a la SMA20", m.s20 ? `Cierre < SMA20 (${f(m.s20)})` : ""];
    return ["", ""];
  }

  const QM_DEFAULTS = { top_pct: 0.02, adr_min: 0.05, prior_move_min: 0.30, base_min: 5, base_max: 42, retrace_max: 0.5, tight_max: 0.8 };
  const QM_HARD = ["leader", "adr", "prior_move", "base"];
  const sgn0 = (x) => { const v = x * 100; return (v >= 0 ? "+" : "") + v.toFixed(0) + "%"; };

  // Igual que radar/qullamaggie.py: evaluate.
  function qmEvaluate(m, st, market, perfCut, qcfg) {
    const q = { ...QM_DEFAULTS, ...(qcfg || {}) };
    const checks = [];
    const add = (key, ok, label, value) => checks.push({ key, ok, hard: QM_HARD.includes(key), label, value });
    const top = (q.top_pct * 100).toFixed(0) + "%";
    const rets = [["1 m", m.r1m, "r1m"], ["3 m", m.r3m, "r3m"], ["6 m", m.r6m, "r6m"]];
    if (perfCut) {
      const hits = rets.filter(([, r, k]) => r !== null && perfCut[k] !== null && perfCut[k] !== undefined && r >= perfCut[k]).map(([lab, r]) => `${lab} ${sgn0(r)}`);
      add("leader", hits.length > 0, `Entre el ${top} que más sube a 1, 3 o 6 meses`,
        hits.length ? "sí: " + hits.join(", ") : "no: " + rets.filter(([, r]) => r !== null).map(([lab, r]) => `${lab} ${sgn0(r)}`).join(", "));
    } else add("leader", null, `Entre el ${top} que más sube a 1, 3 o 6 meses`, "sin datos del universo");
    add("adr", m.adr_pct >= q.adr_min, `ADR ≥ ${pctEs(q.adr_min, 0)} (valor rápido)`, pctEs(m.adr_pct));
    add("prior_move", m.prior_move >= q.prior_move_min, `Subida previa ≥ ${pctEs(q.prior_move_min, 0)} en 1-3 meses`, pctEs(m.prior_move));
    add("base", m.blen >= q.base_min && m.blen <= q.base_max, "Consolidación de 2 semanas a 2 meses (flag desde 5 sesiones)", `${m.blen} sesiones`);
    add("orderly", m.retrace === null ? null : m.retrace <= q.retrace_max, `Retroceso ordenado (corrige ≤ ${pctEs(q.retrace_max, 0)} de la subida)`,
      m.retrace === null ? "sin datos" : `corrige el ${pctEs(m.retrace, 0)}`);
    add("higher_lows", m.higher_lows, "Mínimos crecientes en la base", m.higher_lows ? "sí" : (m.higher_lows === false ? "no" : "base corta"));
    add("tight", m.tight_ratio === null ? null : m.tight_ratio <= q.tight_max, "Rango que se estrecha",
      m.tight_ratio === null ? "base corta" : `rango reciente al ${pctEs(m.tight_ratio, 0)} del inicial`);
    const surf20 = !!(m.s20 && m.C >= m.s20 && m.s20up && m.s10up);
    const surf50 = !!(m.s50 && m.C >= m.s50 && m.s50up);
    add("ma_surf", surf20 || surf50, "Surfea medias ascendentes (SMA10 y SMA20, o SMA50)", surf20 ? "SMA10 y SMA20" : (surf50 ? "SMA50" : "no"));
    const hardFail = checks.some((x) => x.hard && x.ok === false);
    const softFail = checks.some((x) => !x.hard && x.ok === false);
    const verdict = hardFail ? "No cumple" : (softFail || !market || market.light !== "verde") ? "Con reservas" : "Cumple";
    const adr = m.adr_pct, ext = m.C / m.P - 1;
    let trigger = null, note = "Sin setup de entrada";
    if ((st === "CONFIRMADA" || st === "TEMPRANA") && ext > adr) note = "Ya está a más de 1 ADR del nivel de ruptura: no perseguir; esperar una nueva consolidación";
    else if (st === "CONFIRMADA" || st === "TEMPRANA") { trigger = m.high; note = "Ruptura ya iniciada: entrar solo si supera el máximo de hoy en el rango de apertura (ORH)"; }
    else if (st === "PRE-BREAKOUT" || st === "RETEST") {
      trigger = m.P;
      note = m.level_kind === "línea" ? "Entrar el día que supere la resistencia descendente (su valor baja cada sesión), en el ORH"
        : "Entrar el día que supere la resistencia, en el ORH";
    }
    const trail = adr >= q.adr_min ? "SMA10" : "SMA20";
    return { verdict, checks, adr_pct: adr, trigger, entry_note: note, stop_max: trigger ? trigger * (1 - adr) : null,
      trail_ma: trail, trail_value: trail === "SMA10" ? m.s10 : m.s20 };
  }

  // Divisas con unidad menor (peniques, centavos, agorot): base y escala.
  const MINOR = { GBp: ["GBP", 0.01], GBX: ["GBP", 0.01], ZAc: ["ZAR", 0.01], ILA: ["ILS", 0.01] };

  /** Divisa de un ticker: la que informa Yahoo o, si falta, la del sufijo de la bolsa. */
  function currencyOf(sym, meta, E) {
    const suf = sym.includes(".") && !sym.startsWith("^") ? sym.split(".").pop() : "";
    return (meta && meta.currency) || E.currency_by_suffix[suf] || "USD";
  }

  /** Par de Yahoo para convertir una divisa a USD y escala (null si ya está en el radar). */
  function fxNeed(cur, fx) {
    if (fx[cur] !== undefined) return null;
    const [base, scale] = MINOR[cur] || [cur, 1];
    if (fx[base] !== undefined) return null;
    return { pair: `${base}USD=X`, base, scale };
  }

  function fxFactor(cur, fx) {
    if (fx[cur] !== undefined) return fx[cur];
    const [base, scale] = MINOR[cur] || [cur, 1];
    return fx[base] !== undefined ? fx[base] * scale : null;
  }

  /** Prepara las velas del Worker como el motor diario: completa la última sesión si Yahoo la
   * omite en la serie (la toma de los metadatos) y descarta la barra de una sesión aún abierta. */
  function prepareSeries(k, nowSec) {
    const s = { symbol: k.symbol, meta: k.meta || {}, t: [...k.t], o: [...k.o], h: [...k.h], l: [...k.l], c: [...k.c], v: [...k.v] };
    const m = s.meta, g = m.gmtoffset || 0;
    const iso = (sec) => new Date((sec + g) * 1000).toISOString().slice(0, 10);
    if (m.regularMarketTime && isNum(m.regularMarketPrice) && isNum(m.dayHigh) && isNum(m.dayLow)) {
      const d = iso(m.regularMarketTime);
      if (s.t.length && d > s.t[s.t.length - 1]) {
        s.t.push(d); s.o.push(NaN); s.h.push(m.dayHigh); s.l.push(m.dayLow); s.c.push(m.regularMarketPrice);
        s.v.push(m.dayVolume || 0);
      }
    }
    let partial = false;
    if (m.sessionEnd && s.t.length) {
      const last = s.t[s.t.length - 1];
      if (last === iso(m.sessionEnd) && nowSec < m.sessionEnd + 1200) {
        partial = true;
        for (const key of ["t", "o", "h", "l", "c", "v"]) s[key].pop();
      }
    }
    return { series: s, partial };
  }

  /** Evalúa un ticker cualquiera con el contexto del día (bloque `engine` de latest.json).
   * Devuelve una ficha con el mismo formato que las del radar. */
  function evaluateTicker(k, ctx) {
    const E = ctx.settings;
    const w = E.windows, cfg = E.breakout, flt = E.filters;
    const m = compute(k.symbol, k, w);
    if (!m) return null;
    const sym = k.symbol;
    const suf = sym.includes(".") && !sym.startsWith("^") ? sym.split(".").pop() : "";
    const cur = currencyOf(sym, k.meta, E);
    const fx = fxFactor(cur, ctx.fx);
    const mdvUsd = fx ? m.mdv * fx : null, priceUsd = fx ? m.C * fx : null;
    const bsym = E.benchmarks.by_suffix[suf] || E.benchmarks.default;
    const b = ctx.benchmarks[bsym] || {};
    const rs1 = rel(m.r1m, b.r1m ?? null), rs3 = rel(m.r3m, b.r3m ?? null), rs6 = rel(m.r6m, b.r6m ?? null);
    const rsc = rsComposite(rs1, rs3, rs6);
    const dist = ctx.rs_dist || [];
    let lo = 0, hi = dist.length;  // número de valores del universo líquido con RS ≤ la de este
    while (lo < hi) { const mid = (lo + hi) >> 1; if (dist[mid] <= rsc + 5e-7) lo = mid + 1; else hi = mid; }  // rs_dist va redondeado a 6 decimales
    const rsPct = dist.length ? Math.max(1, lo) / dist.length : 0;
    const cl = classify(m, mdvUsd, priceUsd, cfg, flt);
    const inv = invalidation(m, cl.state);
    const sc = score(m, cl.state, rsPct, mdvUsd || 0, null);
    const [rk, rkp] = risk(m, inv, null, false, mdvUsd || 0, E.risk);
    const [conf, inval] = conditions(m, cl.state, inv);
    return {
      sym, theme: null, name: (k.meta && k.meta.name) || sym, exchange: (k.meta && k.meta.exchange) || "", country: "",
      currency: cur, date: m.date, close: m.C, d1: m.d1, state: cl.state, why: cl.why, excluded: "",
      score: sc.total, components: sc, pivot: m.P, pivot_date: m.piv_date, dist: m.C / m.P - 1, base_len: m.blen,
      depth: m.depth, inv, inv_pct: inv ? inv / m.C - 1 : null, inv_atr: inv ? (m.C - inv) / m.atr : null,
      atr: m.atr, atr_pct: m.atr_pct, vol: m.vol, v20: m.v20, rvol: m.rvol, vdry: m.vdry, rs_pct: rsPct,
      r1m: m.r1m, r3m: m.r3m, r6m: m.r6m, rs1, rs3, rs6, dhi: m.dhi, hi52: m.hi52, s10: m.s10, s20: m.s20,
      s50: m.s50, s200: m.s200, adr_pct: m.adr_pct, mdv_usd: mdvUsd, catalyst: "", risk: rk, risk_points: rkp,
      confirm: conf, invalidate: inval, qm: qmEvaluate(m, cl.state, ctx.qm_market, ctx.perf_cut, ctx.qullamaggie),
      peak: m.peak, level_kind: m.level_kind, line: m.line, touch_date: m.touch_date, retrace: m.retrace,
      tight_ratio: m.tight_ratio, prior_move: m.prior_move,
      benchmark: bsym, live: true,
    };
  }

  const api = { compute, classify, invalidation, score, risk, conditions, qmEvaluate, evaluateTicker, prepareSeries,
    currencyOf, fxNeed, fxFactor, rel, rsComposite };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.RadarEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
