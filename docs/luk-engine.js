/* Sistema de Martin Luk en el navegador: el mismo análisis que radar/luk.py, sobre las velas del kit
   (docs/data/live.json) más la vela de hoy, para recalcular setups, termómetro y contexto en directo.
   Cualquier cambio aquí debe reflejarse en radar/luk.py (prueba de paridad: tests/test_luk_parity.py). */
(function (root) {
  "use strict";
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const ORDER = ["EMA 9", "EMA 21", "AVWAP"];
  const SETUPS = ["L1", "L1b"];
  const TRIGGER = { L1: "Rotura del máximo anterior / reclaim VWAP-AVWAP", L1b: "Reclaim de la EMA 21",
    L3: "Rotura de {x} solo con stop <= 1,5%" };

  // EMA de hoy a partir de la de ayer (alfa 2/(n+1)).
  const emaNext = (prev, x, n) => (isNum(prev) ? (2 / (n + 1)) * x + (1 - 2 / (n + 1)) * prev : NaN);

  /** Serie con la vela de hoy añadida: arrays alineados y colas de EMA (las 5 últimas del kit + hoy). */
  function withBar(kit, bar) {
    const t = [...kit.t], o = [...kit.o], h = [...kit.h], l = [...kit.l], c = [...kit.c], v = [...kit.v], va = [...kit.v];
    if (bar) { t.push(bar.t); o.push(bar.o); h.push(bar.h); l.push(bar.l); c.push(bar.c); v.push(bar.vp); va.push(bar.v); }
    const n = c.length, s = n - 1;
    const em = (tail, N) => {
      const a = new Array(n).fill(NaN);
      const end = bar ? n - 2 : n - 1;
      tail.forEach((x, i) => { a[end - tail.length + 1 + i] = isNum(x) ? x : NaN; });
      if (bar) a[s] = emaNext(a[s - 1], c[s], N);
      return a;
    };
    return { t, o, h, l, c, v, va, n, s, e9: em(kit.e9, 9), e21: em(kit.e21, 21), e50: em(kit.e50, 50), e150: em(kit.e150, 150) };
  }

  const meanR = (a, i, j) => { let x = 0; for (let k = i; k <= j; k++) x += a[k]; return x / (j - i + 1); };
  const adrAt = (S, i) => { let x = 0; for (let k = i - 19; k <= i; k++) x += S.h[k] / S.l[k]; return x / 20 - 1; };
  const m50At = (S, i) => (i >= 50 ? meanR(S.v, i - 50, i - 1) : NaN);
  const up = (e, s, k) => s - k >= 0 && isNum(e[s - k]) && e[s] > e[s - k];

  function avwap(S, a, i) {
    let pv = 0, vv = 0;
    for (let k = a; k <= i; k++) { const tp = (S.h[k] + S.l[k] + S.c[k]) / 3; pv += tp * S.va[k]; vv += S.va[k]; }
    return vv > 0 ? pv / vv : (S.h[i] + S.l[i] + S.c[i]) / 3;
  }

  /** Análisis de un líder en la última vela (la de hoy si se pasa `bar`). Mismo resultado que luk.analyze. */
  function analyze(kit, bar, q, scanOk = true) {
    const S = withBar(kit, bar);
    const { o, h, l, c, v, s } = S;
    if (s < 60) return null;
    const adr = adrAt(S, s);
    if (!isNum(adr) || adr <= 0 || !isNum(S.e50[s])) return null;
    const unit = adr * c[s], k = q.ema_rise;
    const out = { date: S.t[s], close: c[s], high_today: h[s], low_today: l[s], adr, scan: !!scanOk };
    const W = q.catalyst_window;
    const isEp = (i) => i >= 1 && c[i - 1] > 0 && isNum(m50At(S, i)) && o[i] / c[i - 1] - 1 >= q.ep_gap && v[i] >= q.ep_vol_mult * m50At(S, i);
    const isBr = (i) => {
      if (i < q.breakout_lookback) return false;
      let mx = -Infinity; for (let j = i - q.breakout_lookback; j < i; j++) mx = Math.max(mx, h[j]);
      const m = m50At(S, i);
      return isNum(m) && c[i] > mx && v[i] >= q.breakout_vol_mult * m;
    };
    let le = -1, lb = -1;
    for (let i = s; i > s - W && i >= 0; i--) { if (le < 0 && isEp(i)) le = i; if (lb < 0 && isBr(i)) lb = i; }
    const ep60 = le >= 0;
    let anc, kind;
    if (ep60) { anc = le; kind = "EP"; } else if (lb >= 0) { anc = lb; kind = "ruptura"; } else {
      anc = s - 19; for (let i = s - 18; i <= s; i++) if (l[i] < l[anc]) anc = i;
      kind = "mínimo 20";
    }
    const av = avwap(S, anc, s);
    const m50s = m50At(S, s);
    Object.assign(out, { anchor: kind, anchor_date: S.t[anc], anchor_since: s - anc, avwap: av, ep_today: isEp(s),
      gap: c[s - 1] > 0 ? o[s] / c[s - 1] - 1 : null, vol_x: m50s > 0 ? v[s] / m50s : null });
    const { e9, e21, e50, e150 } = S;
    const e21up = up(e21, s, k), e50up = up(e50, s, k), e9up = up(e9, s, k);
    const trend = e21[s] > e50[s] && e21up && e50up && c[s] > e50[s];
    const hi52 = Math.max(kit.hi252 || 0, h[s]);
    const dist52 = hi52 > 0 ? 1 - c[s] / hi52 : null;
    const near52 = dist52 !== null && (dist52 <= q.max_dist_52w_high || ep60);
    let p = s - q.high_window + 1;
    for (let i = p; i <= s; i++) if (h[i] >= h[p]) p = i;
    const days = s - p, high20 = h[p];
    const a0 = Math.max(0, p - q.leg_lookback);
    let legLo = Infinity; for (let i = a0; i <= p; i++) legLo = Math.min(legLo, l[i]);
    const leg = high20 / legLo - 1, legAdr = (high20 - legLo) / unit;
    const legOk = leg >= q.leg_min && legAdr >= q.leg_adr_min;
    const why = !scanOk ? "no está en el escáner de momentum" : !trend ? "medias (EMA 21 > EMA 50, ambas al alza y cierre > EMA 50)"
      : !near52 ? `a ${(dist52 * 100).toFixed(0)}% del máximo de 52 semanas` : !legOk ? "tramo previo < 20% o < 4 ADR" : "";
    const leader = !why;
    Object.assign(out, { leader, why, trend, e9up, e21up, e50up, ema9: e9[s], ema21: e21[s], ema50: e50[s],
      ema150: isNum(e150[s]) ? e150[s] : null, dist52, ep60, high20, high_date: S.t[p], days, leg, leg_lo: legLo, leg_adr: legAdr });
    let pullLo = l[s];
    if (days >= 1) { pullLo = Infinity; for (let i = p + 1; i <= s; i++) pullLo = Math.min(pullLo, l[i]); }
    const depthAdr = (high20 - pullLo) / high20 / adr;
    const retrace = high20 > legLo ? (high20 - pullLo) / (high20 - legLo) : 1;
    const sups = [["EMA 9", e9[s]], ["EMA 21", e21[s]], ["AVWAP", av]];
    let near = sups[0];
    for (const x of sups) if (Math.abs(c[s] - x[1]) < Math.abs(c[s] - near[1])) near = x;
    const distAdr = Math.abs(c[s] - near[1]) / unit, tol = q.touch_adr * unit;
    const touched = (i) => {
      const t = [];
      for (const [name, val] of [["EMA 9", e9[i]], ["EMA 21", e21[i]], ["AVWAP", anc <= i ? avwap(S, anc, i) : null]]) {
        if (isNum(val) && l[i] <= val + tol) t.push(name);
      }
      return t.length && !(t.length === 1 && t[0] === "EMA 9" && i - p < 3) ? t : [];
    };
    const tset = new Set();
    for (const i of [s - 1, s]) if (i > p) touched(i).forEach((x) => tset.add(x));
    const touch = ORDER.filter((x) => tset.has(x));
    const zone = touch.length > 0 || distAdr <= q.support_adr;
    const recovery = c[s] > h[s - 1];
    const pidx = []; for (let i = p + 1; i <= s; i++) if (!(i === s && recovery)) pidx.push(i);
    const volRatio = pidx.length && m50s > 0 ? pidx.reduce((x, i) => x + v[i], 0) / pidx.length / m50s : null;
    const inside = h[s] <= h[s - 1] && l[s] >= l[s - 1];
    let nr7 = true; const r0 = h[s] - l[s]; for (let i = s - 6; i < s; i++) if (h[i] - l[i] < r0) nr7 = false;
    Object.assign(out, { pull_lo: pullLo, depth: 1 - pullLo / high20, depth_adr: depthAdr, retrace, support: near[0],
      support_value: near[1], dist_adr: distAdr, touch, zone, recovery, vol_ratio: volRatio, inside, nr7,
      wide_day: (c[s] - l[s]) / c[s] });
    const baseOk = leader && days >= q.pull_min && days <= q.pull_max && depthAdr >= q.depth_adr_min && depthAdr <= q.depth_adr_max
      && retrace <= q.retrace_max;
    let setup = null, fail = "";
    if (baseOk && c[s] >= e21[s] && zone) setup = "L1";
    else if (baseOk && e21[s] - q.below21_adr * unit <= c[s] && c[s] < e21[s] && c[s] > e50[s]) setup = "L1b";
    else if (leader) {
      const n10 = q.l3_range_sessions;
      let hi10 = -Infinity, lo10 = Infinity;
      for (let i = s - n10 + 1; i <= s; i++) { hi10 = Math.max(hi10, h[i]); lo10 = Math.min(lo10, l[i]); }
      Object.assign(out, { base_hi: hi10, base_range_adr: (hi10 - lo10) / unit });
      if ((hi10 - lo10) / unit <= q.l3_range_adr && c[s] >= hi10 * (1 - q.l3_near_high)) setup = "L3";
    }
    if (!setup && leader) {
      fail = !(days >= q.pull_min && days <= q.pull_max) ? "días desde el máximo fuera de 2-8"
        : !(depthAdr >= q.depth_adr_min && depthAdr <= q.depth_adr_max) ? `corrección de ${depthAdr.toFixed(1)} ADR (pide 1-3)`
          : retrace > q.retrace_max ? `corrige el ${(retrace * 100).toFixed(0)}% del tramo (máx. 62%)`
            : c[s] < e21[s] ? "más de 0,75 ADR bajo la EMA 21 o bajo la EMA 50" : "fuera de la zona de soporte";
    }
    out.setup = setup; out.setup_why = fail;
    return out;
  }

  function levels(a, q) {
    const st = a.setup;
    let entry, level;
    if (st === "L1") { entry = a.high_today + q.tick; level = `${a.support} ${a.support_value.toFixed(2)}`; }
    else if (st === "L1b") { entry = a.ema21 + q.tick; level = `EMA 21 ${a.ema21.toFixed(2)}`; }
    else { entry = a.base_hi + q.tick; level = `Máx. base ${a.base_hi.toFixed(2)}`; }
    const sp = q.stop_target_pct / 100;
    return { entry, stop: entry * (1 - sp), stop_min: entry * (1 - q.stop_max_pct / 100), stop_pct: q.stop_target_pct,
      size_pct: q.risk_pct / q.stop_target_pct * 100, r3: entry * (1 + 3 * sp), r5: entry * (1 + 5 * sp), level,
      trigger: TRIGGER[st].replace("{x}", entry.toFixed(2)) };
  }

  function score(a, rs, themeN, earnSessions, earnKnown, q) {
    const vr = a.vol_ratio;
    const dry = isNum(vr) ? Math.min(1, Math.max(0, (1 - vr) / 0.5)) : 0;
    const prox = Math.min(1, Math.max(0, 1 - a.dist_adr));
    const bonus = q.bonus * (((a.inside || a.nr7) ? 1 : 0) + (a.e9up ? 1 : 0) + (a.days >= q.pull_best_min && a.days <= q.pull_best_max ? 1 : 0));
    const pull = Math.min(1, (dry + prox) / 2 + bonus);
    const theme = Math.min(themeN, q.theme_cap) / q.theme_cap;
    const cat = a.anchor === "EP" || a.anchor === "ruptura" ? Math.max(0, 1 - a.anchor_since / q.catalyst_window) : 0;
    const rsv = isNum(rs) ? rs : 0;
    const base = 100 * (q.w_rs * rsv + q.w_pull * pull + q.w_theme * theme + q.w_catalyst * cat);
    let mult = 1; const flags = [];
    if (isNum(earnSessions) && earnSessions >= 0 && earnSessions <= q.earnings_window) {
      mult *= q.earnings_mult; flags.push(earnSessions === 0 ? "resultados hoy" : `resultados en ${earnSessions} sesiones`);
    } else if (!earnKnown) flags.push("verificar resultados");
    if (a.wide_day > q.wide_day_pct) { mult *= q.wide_day_mult; flags.push("requiere gatillo intradía"); }
    if (!isNum(rs)) flags.push("verificar fuerza relativa");
    return { score: Math.round(base * mult * 10) / 10, base: Math.round(base * 10) / 10, mult, flags,
      parts: { rs: isNum(rs) ? rs : null, pull, dry, prox, bonus, theme, cat } };
  }

  /** Sano / dañado / mixto con la vela de hoy, a partir del kit de salud (colas de EMA, ADR y huecos). */
  function health(kh, bar, q) {
    if (!bar) return kh.status;
    const c = bar.c, e9p = kh.e9[kh.e9.length - 1], e21p = kh.e21[kh.e21.length - 1];
    const e9 = emaNext(e9p, c, 9), e21 = emaNext(e21p, c, 21);
    const e9b = kh.e9[kh.e9.length - 3], e21b = kh.e21[kh.e21.length - 3];   // hace 3 sesiones contando hoy
    const gapToday = isNum(bar.o) && kh.c > 0 && bar.o / kh.c - 1 <= -kh.adr;
    if (kh.gd || gapToday || (c < e9 && c < e21 && e9 < e9b && e21 < e21b)) return "dañado";
    if (c > e9 && c > e21 && e9 > e9b && e21 > e21b) return "sano";
    return "mixto";
  }

  function context(kh, bar, q) {
    const c = bar ? bar.c : kh.c;
    const last = (tail) => tail[tail.length - 1];
    const vals = {};
    for (const n of [9, 21, 50, 150]) vals[n] = bar ? emaNext(last(kh[`e${n}`]), c, n) : last(kh[`e${n}`]);
    const order = Object.entries(vals).filter(([, x]) => isNum(x)).sort((a, b) => b[1] - a[1]).map(([n]) => n).join(" > ");
    const out = { close: c, date: bar ? bar.t : null, status: health(kh, bar, q), order, aligned: order === "9 > 21 > 50 > 150" };
    for (const n of [9, 21, 50, 150]) { out[`vs${n}`] = isNum(vals[n]) ? c / vals[n] - 1 : null; out[`ema${n}`] = vals[n]; }
    return out;
  }

  function mode(counts, q) {
    const n = counts.n || 0;
    if (!n) return "SIN DATOS";
    if (counts.good / n > q.long_healthy) return "LARGO";
    if (counts.bad / n >= q.short_damaged) return "CORTO";
    return "NEUTRO";
  }

  /** Sesiones de EE. UU. desde mañana hasta `target` incluido (0 = hoy; null si ya pasó). */
  function sessionsUntil(todayIso, targetIso, holidays) {
    if (!targetIso || targetIso < todayIso) return null;
    const hol = new Set(holidays || []);
    let n = 0; const d = new Date(todayIso + "T12:00:00Z");
    while (d.toISOString().slice(0, 10) < targetIso) {
      d.setUTCDate(d.getUTCDate() + 1);
      const iso = d.toISOString().slice(0, 10), wd = d.getUTCDay();
      if (wd !== 0 && wd !== 6 && !hol.has(iso)) n++;
    }
    return n;
  }

  const api = { analyze, levels, score, health, context, mode, sessionsUntil, emaNext, SETUPS, TRIGGER };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.LukEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
