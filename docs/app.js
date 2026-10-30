/* Radar de rupturas — dashboard estático. Lee docs/data/latest.json y el histórico diario. */
(() => {
  "use strict";

  const STATE_LABEL = {
    "CONFIRMADA": "Confirmada", "TEMPRANA": "Temprana", "PRE-BREAKOUT": "Pre-breakout",
    "RETEST": "Retest", "EXTENDIDA": "Extendida", "EN BASE": "En base", "DESCARTADA": "Descartada",
  };
  const DS_LABEL = { "NUEVA": "Nueva", "CONTINÚA": "Continúa", "MEJORA": "Mejora", "DETERIORA": "Deteriora" };
  const STATE_ORDER = ["CONFIRMADA", "TEMPRANA", "RETEST", "PRE-BREAKOUT"];
  const TV_PREFIX = {
    L: "LSE", DE: "XETR", PA: "EURONEXT", AS: "EURONEXT", BR: "EURONEXT", LS: "EURONEXT", MI: "MIL",
    MC: "BME", SW: "SIX", ST: "OMXSTO", CO: "OMXCOP", OL: "OSL", HE: "OMXHEX", VI: "VIE", WA: "GPW",
    T: "TSE", KS: "KRX", KQ: "KRX", TW: "TWSE", TWO: "TPEX", HK: "HKEX", AX: "ASX", TO: "TSX", V: "TSXV",
    NS: "NSE", BO: "BSE",
  };
  const LEVEL_KIND = { "máximo": "techo plano (máximo de la base)", "línea": "resistencia descendente", "rango": "máximo de las últimas sesiones" };
  const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  // ---------- utilidades ----------
  const $ = (sel, el = document) => el.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const num = (x, d = 2) => isNum(x) ? x.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: "always" }) : "—";
  const pct = (x, d = 1, sign = true) => isNum(x) ? (sign && x > 0 ? "+" : "") + num(x * 100, d) + "%" : "—";
  const cls = (x) => !isNum(x) ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "";
  const priceDec = (x, cur) => (["JPY", "KRW", "INR", "TWD"].includes(cur) && x >= 1000) ? 0 : 2;
  const price = (x, cur) => isNum(x) ? num(x, priceDec(x, cur)) : "—";
  const dateEs = (iso, withDay = false) => {
    if (!iso) return "—";
    const d = new Date(iso + "T12:00:00");
    const s = `${d.getDate()}-${MONTHS[d.getMonth()]}`;
    return withDay ? `${["dom", "lun", "mar", "mié", "jue", "vie", "sáb"][d.getDay()]} ${s}` : s;
  };
  const stClass = (s) => "st-" + String(s).replace(/\s+/g, "-");
  const chip = (s) => `<span class="chip ${stClass(s)}">${esc(STATE_LABEL[s] || s)}</span>`;
  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } },
  };
  const tvUrl = (sym) => {
    const [base, suf] = sym.includes(".") ? sym.split(".") : [sym, ""];
    let b = base.replace("-", ".");
    if (suf === "HK") b = String(parseInt(b, 10));
    const p = TV_PREFIX[suf];
    return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(p ? `${p}:${b}` : b)}`;
  };
  const yfUrl = (sym) => `https://finance.yahoo.com/quote/${encodeURIComponent(sym)}`;
  const safeName = (sym) => sym.replace(/[^A-Za-z0-9_-]/g, "_");  // igual que radar/pipeline.py
  const reducedMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Datos del día y caché de fichas por valor.
  let D = null, BYS = {}, SCORE_HIST = {};
  const tickerCache = new Map();
  const loadTicker = (sym) => {
    if (!tickerCache.has(sym)) {
      tickerCache.set(sym, getJSON(`data/c/${safeName(sym)}.json`).catch((e) => { tickerCache.delete(sym); throw e; }));
    }
    return tickerCache.get(sym);
  };

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }

  // ---------- gráficos mínimos en SVG ----------
  function ladder(c) {
    const W = 150, H = 28, pad = 6;
    const inv = isNum(c.inv) ? c.inv : null;
    const vals = [c.close, c.pivot].concat(inv ? [inv] : []);
    const lo = Math.min(...vals) - 0.6 * c.atr, hi = Math.max(...vals) + 0.6 * c.atr;
    const x = (v) => pad + (v - lo) / (hi - lo || 1) * (W - 2 * pad);
    const atrDist = (c.close - c.pivot) / (c.atr || 1);
    const col = getComputedStyle(document.documentElement);
    const tip = `Cierre ${price(c.close, c.currency)} · nivel de ruptura ${price(c.pivot, c.currency)}${inv ? " · invalidación " + price(inv, c.currency) : ""} · ${num(atrDist, 1)} ATR desde el nivel de ruptura`;
    return `<svg class="ladder ${stClass(c.state)}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(tip)}">
      <title>${esc(tip)}</title>
      <line x1="${pad}" x2="${W - pad}" y1="${H / 2}" y2="${H / 2}" stroke="${col.getPropertyValue("--rule")}" stroke-width="2"/>
      ${inv ? `<rect x="${Math.min(x(inv), x(c.pivot))}" y="${H / 2 - 3}" width="${Math.abs(x(c.pivot) - x(inv))}" height="6" fill="${col.getPropertyValue("--neg")}" opacity="0.18"/>
      <line x1="${x(inv)}" x2="${x(inv)}" y1="${H / 2 - 6}" y2="${H / 2 + 6}" stroke="${col.getPropertyValue("--neg")}" stroke-width="2"/>` : ""}
      <line x1="${x(c.pivot)}" x2="${x(c.pivot)}" y1="2" y2="${H - 2}" stroke="${col.getPropertyValue("--pivot")}" stroke-width="2.5"/>
      <circle cx="${x(c.close)}" cy="${H / 2}" r="5.5" style="fill:var(--st)" stroke="${col.getPropertyValue("--surface")}" stroke-width="1.5"/>
    </svg>`;
  }

  function spark(values, w = 90, h = 22) {
    const v = values.filter(isNum);
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v);
    const pts = v.map((y, i) => `${(i / (v.length - 1) * (w - 4) + 2).toFixed(1)},${(h - 3 - (y - lo) / (hi - lo || 1) * (h - 6)).toFixed(1)}`);
    const last = pts[pts.length - 1].split(",");
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <polyline points="${pts.join(" ")}" fill="none" style="stroke:var(--muted)" stroke-width="1.5"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="2.5" style="fill:var(--pivot)"/></svg>`;
  }


  // ---------- gráfico de velas (TradingView Lightweight Charts, código abierto) ----------
  // Copia local (la descarga el flujo de publicación) y, si falta, la CDN oficial.
  const LWC_URLS = ["vendor/lightweight-charts.js",
    "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"];
  let lwcPromise = null;
  const loadScript = (src) => new Promise((ok, ko) => {
    const sc = document.createElement("script");
    sc.src = src; sc.async = true;
    sc.onload = () => (window.LightweightCharts ? ok(window.LightweightCharts) : ko(new Error("librería vacía")));
    sc.onerror = () => { sc.remove(); ko(new Error("no se pudo cargar " + src)); };
    document.head.appendChild(sc);
  });
  const loadLWC = () => lwcPromise || (lwcPromise = (async () => {
    if (window.LightweightCharts) return window.LightweightCharts;
    for (const u of LWC_URLS) { try { return await loadScript(u); } catch { /* siguiente */ } }
    lwcPromise = null;
    throw new Error("no se pudo cargar la librería de gráficos");
  })());
  const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const alpha = (hex, a) => {
    const h = hex.replace("#", "");
    if (h.length !== 6) return hex;
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
  };
  const smaSeries = (t, c, n) => {
    const out = []; let sum = 0;
    for (let i = 0; i < c.length; i++) {
      sum += c[i]; if (i >= n) sum -= c[i - n];
      if (i >= n - 1) out.push({ time: t[i], value: sum / n });
    }
    return out;
  };

  // Medias del gráfico: las que usa Qullamaggie (10, 20 y 50) y la de 200 a demanda.
  const MAS = [[10, "--ma10", 1.5], [20, "--ma20", 1.5], [50, "--ma50", 2], [200, "--ma200", 1.5]];

  async function drawChart(el, c, kPromise) {
    try {
      const [LWC, k] = await Promise.all([loadLWC(), kPromise]);
      if (!k || !k.t || !k.t.length) { el.innerHTML = `<p class="empty">Sin velas para ${esc(c.sym)}.</p>`; return; }
      el.innerHTML = "";
      const col = { bg: cssVar("--surface"), text: cssVar("--muted"), grid: cssVar("--soft"), rule: cssVar("--rule"),
        up: cssVar("--pos"), down: cssVar("--neg"), pivot: cssVar("--pivot") };
      const chart = LWC.createChart(el, {
        height: el.clientWidth < 600 ? 300 : 380,
        layout: { background: { color: col.bg }, textColor: col.text, fontFamily: "Archivo, system-ui, sans-serif" },
        grid: { vertLines: { color: col.grid }, horzLines: { color: col.grid } },
        rightPriceScale: { borderColor: col.rule }, timeScale: { borderColor: col.rule, rightOffset: 4 },
        crosshair: { mode: 0 }, localization: { locale: "es-ES" },
      });
      const open = (i) => (isNum(k.o[i]) ? k.o[i] : k.c[i]);
      const candles = chart.addCandlestickSeries({ upColor: col.up, downColor: col.down, borderVisible: false,
        wickUpColor: col.up, wickDownColor: col.down, priceLineVisible: false });
      candles.setData(k.t.map((t, i) => ({ time: t, open: open(i), high: k.h[i], low: k.l[i], close: k.c[i] })));
      candles.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
      if (k.v && k.v.length) {
        const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "", lastValueVisible: false, priceLineVisible: false });
        chart._volSeries = vol;
        vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
        vol.setData(k.t.map((t, i) => ({ time: t, value: k.v[i] || 0, color: alpha(k.c[i] >= open(i) ? col.up : col.down, 0.35) })));
      }
      const show200 = store.get("radar.sma200", false);
      el._sma = {};
      MAS.forEach(([n, v, w]) => {
        if (k.c.length < n) return;
        const line = chart.addLineSeries({ color: cssVar(v), lineWidth: w, visible: n !== 200 || show200,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        line.setData(smaSeries(k.t, k.c, n));
        el._sma[n] = line;
      });
      candles.createPriceLine({ price: c.pivot, color: col.pivot, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "Ruptura" });
      if (Array.isArray(c.line) && c.line.length === 2 && c.line[1][0] > c.line[0][0]) {
        // Borde superior de la consolidación desde el máximo de la base (plano o descendente).
        chart.addLineSeries({ color: col.pivot, lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false }).setData(c.line.map(([t, v]) => ({ time: t, value: v })));
      }
      if (isNum(c.peak) && c.peak > c.pivot * 1.02) {
        candles.createPriceLine({ price: c.peak, color: col.text, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "Máx. base" });
      }
      if (isNum(c.inv)) candles.createPriceLine({ price: c.inv, color: col.down, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Invalidación" });
      const n = k.t.length;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 130), to: n + 3 });
      const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
      ro.observe(el);
      el._dispose = () => { ro.disconnect(); chart.remove(); el._candles = null; };
      // Para los precios en vivo: la vela del día se dibuja sobre la última del cierre.
      Object.assign(el, { _candles: candles, _vol: chart._volSeries || null, _sym: c.sym, _lastT: k.t[n - 1], _col: col });
      updateLiveCharts();
    } catch (err) {
      el.innerHTML = `<p class="empty">No se pudo dibujar el gráfico (${esc(err.message)}). Usa el enlace a TradingView.</p>`;
    }
  }

  function chartLegend(c) {
    const on = store.get("radar.sma200", false);
    return `<p class="legend"><span><i style="background:var(--pivot)"></i>Ruptura ${price(c.pivot, c.currency)}${c.level_kind ? ` (${esc(LEVEL_KIND[c.level_kind] || c.level_kind)})` : ""}</span>
      <span><i class="dash"></i>Borde de la consolidación</span>
      <span><i style="background:var(--neg)"></i>Invalidación ${price(c.inv, c.currency)}</span>
      <span><i style="background:var(--ma10)"></i>SMA10</span><span><i style="background:var(--ma20)"></i>SMA20</span>
      <span><i style="background:var(--ma50)"></i>SMA50</span>
      <label class="ma-toggle"><input type="checkbox" class="sma200" ${on ? "checked" : ""}><i style="background:var(--ma200)"></i>SMA200</label></p>`;
  }

  // ---------- plan según las reglas de Qullamaggie ----------
  function qmBlock(c) {
    const q = c.qm, cur = c.currency, K = (D && D.qm_const) || q;
    const acct = store.get("radar.qm.account", 10000), risk = store.get("radar.qm.risk", 0.5);
    const checks = q.checks.map((k) => `<li class="${k.ok === true ? "pos" : k.ok === false ? "neg" : "dim"}">
      <span aria-hidden="true">${k.ok === true ? "✓" : k.ok === false ? "✗" : "·"}</span> ${esc(k.label)}${k.hard ? "" : " <span class=\"dim\">(secundaria)</span>"}: <strong>${esc(k.value)}</strong></li>`).join("");
    return `<div class="qm-box" data-sym="${esc(c.sym)}">
      <h3>Plan según las reglas de Qullamaggie · <span class="qmv qmv-${esc(q.verdict.replace(/\s+/g, "-"))}">${esc(q.verdict)}</span></h3>
      <div class="qm-grid">
        <div><p class="dim">Requisitos del setup (las no marcadas como secundarias son obligatorias)</p><ul class="checks">${checks}</ul></div>
        <div><dl>
          <dt>Entrada</dt><dd>${q.trigger ? `Por encima de <strong>${price(q.trigger, cur)}</strong>` : "—"}<br><span class="dim">${esc(q.entry_note)}</span></dd>
          <dt>Marco temporal</dt><dd>${esc(K.entry_timeframe)}</dd>
          <dt>Stop</dt><dd>${esc(K.stop_rule)}${isNum(q.stop_max) ? `; como máximo ${price(q.stop_max, cur)}` : ""}<br><span class="dim">${esc(K.stop_note)}</span></dd>
          <dt>Salidas</dt><dd><ol class="sells">${(K.sell_plan || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
            <span class="dim">${esc(q.trail_ma)} actual: ${price(q.trail_value, cur)}</span></dd>
          <dt>Horizonte</dt><dd>${esc(K.horizon)}</dd>
        </dl></div>
        <div class="calc"><p><strong>Tamaño de la posición</strong> <span class="dim">(${esc(K.risk_rule)})</span></p>
          <label>Cuenta (${esc(cur === "GBp" ? "GBP" : cur)})<input type="number" min="0" step="100" class="qm-acct" value="${esc(acct)}"></label>
          <label>Riesgo por operación (%)<input type="number" min="0.1" max="1" step="0.05" class="qm-risk" value="${esc(risk)}"></label>
          <p class="qm-out" aria-live="polite"></p></div>
      </div></div>`;
  }
  function qmCalc(box, c) {
    if (!box) return;
    const q = c.qm, out = box.querySelector(".qm-out");
    const upd = () => {
      const acct = parseFloat(box.querySelector(".qm-acct").value) || 0, risk = parseFloat(box.querySelector(".qm-risk").value) || 0;
      store.set("radar.qm.account", acct); store.set("radar.qm.risk", risk);
      if (!q.trigger || !isNum(q.stop_max)) { out.textContent = "Sin entrada definida hoy."; return; }
      const px = c.currency === "GBp" ? q.trigger / 100 : q.trigger, stop = c.currency === "GBp" ? q.stop_max / 100 : q.stop_max;
      const perShare = px - stop;
      const shares = perShare > 0 ? Math.floor((acct * risk / 100) / perShare) : 0;
      const posPct = acct > 0 ? shares * px / acct * 100 : 0;
      out.innerHTML = `Con el stop en el peor caso (1 ADR): <strong>${shares.toLocaleString("es-ES")} acciones</strong>, ${num(shares * px, 0)} de posición (${num(posPct, 1)}% de la cuenta), riesgo ${num(acct * risk / 100, 0)}.` +
        (posPct > 30 ? ` <span class="neg">Supera el 30% de la cuenta: Qullamaggie nunca pasa de ahí de un día para otro (lo habitual es 10-20%).</span>` : "") +
        ` <span class="dim">Si el mínimo real del día está más cerca, el riesgo baja con el mismo número de acciones.</span>`;
    };
    box.addEventListener("input", upd); upd();
  }

  // ---------- secciones ----------
  function renderHeader(d) {
    const m = d.meta;
    const prev = m.previous_session ? ` Comparado con la sesión del ${dateEs(m.previous_session)}.` : " Primer informe: sin comparación previa.";
    $("#session").textContent = `Sesión del ${dateEs(m.session, true)} · ${m.coverage.liquid.toLocaleString("es-ES")} valores líquidos analizados.${prev}`;
    document.title = `Radar de rupturas · ${dateEs(m.session)}`;
  }

  function renderRegime(d, hist) {
    const r = d.regime;
    const ups = r.rules.filter((x) => x.points > 0).map((x) => x.signal.toLowerCase());
    const downs = r.rules.filter((x) => x.points < 0).map((x) => x.signal.toLowerCase());
    const sub = `Puntuación ${r.score > 0 ? "+" : ""}${r.score} sobre ${r.rules.length} señales. ` +
      (r.label === "MIXTO" ? "Las rupturas tienen respaldo donde hay amplitud, pero el riesgo de señal falsa sube fuera de las temáticas líderes."
        : r.label === "FAVORABLE" ? "El contexto respalda las rupturas: participación amplia y volatilidad contenida."
          : "El contexto penaliza las rupturas: conviene exigir más confirmación o esperar.");
    const label = { FAVORABLE: "Favorable", MIXTO: "Mixto", DESFAVORABLE: "Desfavorable" }[r.label] || r.label;
    const idx = r.indices.filter((i) => i.available);
    const br = r.breadth || {};
    const bCell = (k, name) => {
      const b = br[k] || {}; const now = b.now, was = b.t21;
      if (!now) return "";
      return `<div class="cell"><p class="cap">${name}: % sobre SMA50</p>
        <div class="num-big">${num(now.p50 * 100, 0)}%</div>
        <div class="was">Hace 21 sesiones: ${was ? num(was.p50 * 100, 0) + "%" : "—"} · sobre SMA200: ${num(now.p200 * 100, 0)}% · máx./mín. 52s: ${now.nh}/${now.nl}</div></div>`;
    };
    const p50hist = hist.map((h) => h.regime && h.regime.p50_spx);
    $("#regimen").innerHTML = `
      <div class="verdict">
        <div>
          <h2 class="sr">Régimen de mercado</h2>
          <p class="verdict-word" data-v="${esc(r.label)}">${esc(label)}</p>
          <p class="verdict-sub">${esc(sub)}</p>
        </div>
        <ul class="signals" aria-label="Señales del régimen">
          ${r.rules.map((x) => `<li><span class="sig ${x.points > 0 ? "up" : "down"}" aria-hidden="true">${x.points > 0 ? "+" : "−"}</span><span>${esc(x.signal)}${x.points > 0 ? "" : ": no"}</span></li>`).join("")}
        </ul>
      </div>
      <div class="grid2">
        <div>
          <h3>Índices</h3>
          <div class="tbl-wrap"><table>
            <thead><tr><th class="left">Índice</th><th>Cierre</th><th>Fecha</th><th>vs SMA20</th><th>vs SMA50</th><th>vs SMA200</th><th>1 m</th><th>3 m</th><th>Desde máx.</th></tr></thead>
            <tbody>${idx.map((i) => `<tr><td class="left">${esc(i.name)}</td><td>${num(i.close, i.close > 1000 ? 0 : 2)}</td><td class="dim">${dateEs(i.date)}</td>
              <td class="${cls(i.vs20)}">${pct(i.vs20)}</td><td class="${cls(i.vs50)}">${pct(i.vs50)}</td><td class="${cls(i.vs200)}">${pct(i.vs200)}</td>
              <td class="${cls(i.r1m)}">${pct(i.r1m)}</td><td class="${cls(i.r3m)}">${pct(i.r3m)}</td><td class="${cls(i.dhi)}">${pct(i.dhi)}</td></tr>`).join("")}</tbody>
          </table></div>
        </div>
        <div>
          <h3>Amplitud en EE. UU.</h3>
          <div class="breadth">${bCell("SPX", "S&P 500")}${bCell("MID", "S&P 400")}${bCell("SML", "S&P 600")}</div>
          ${p50hist.filter(isNum).length > 1 ? `<p class="lead" style="margin-top:10px">Evolución de la amplitud del S&P 500 en el histórico: ${spark(p50hist, 140, 26)}</p>` : ""}
          ${d.qm_market ? `<p class="qm-light qm-${esc((d.qm_market.light || "").replace("á", "a"))}"><strong>Filtro de mercado Qullamaggie:</strong> ${esc(d.qm_market.text)}${isNum(d.qm_market.close) ? ` (cierre ${num(d.qm_market.close, 0)}; SMA10 ${num(d.qm_market.s10, 0)}; SMA20 ${num(d.qm_market.s20, 0)})` : ""}.</p>` : ""}
          <p class="lead" style="margin-top:10px">VIX ${num(r.vix.vix, 1)} · VIX 3 meses ${num(r.vix.vix3m, 1)}${isNum(r.vix.vix) && isNum(r.vix.vix3m) ? (r.vix.vix < r.vix.vix3m ? " (contango: sin estrés agudo)" : " (invertida: estrés)") : ""}.</p>
        </div>
      </div>`;
    // h2 accesible pero oculto visualmente: el veredicto hace de titular
    const h = $("#regimen h2.sr"); h.style.position = "absolute"; h.style.left = "-9999px";
  }

  function renderPriority(d, byS) {
    const list = d.lists.priority.map((s) => byS[s]).filter(Boolean);
    $("#prioridad").innerHTML = `<h2>Prioritarias para estudiar el gráfico</h2>
      <p class="lead">Una por temática, sin riesgo alto ni resultados en los próximos 7 días. Ninguna es una señal de compra: son las estructuras más limpias del día.</p>
      ${list.length ? `<div class="prio">${list.map((c) => `
        <article class="${stClass(c.state)}" style="--st:var(--${{ CONFIRMADA: "s-conf", TEMPRANA: "s-early", "PRE-BREAKOUT": "s-pre", RETEST: "s-retest" }[c.state] || "pivot"})">
          <div class="tk"><a href="${tvUrl(c.sym)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none">${esc(c.sym)}</a></div>
          <div class="nm">${esc(c.name)}</div>
          ${chip(c.state)} <span class="dim" style="font-size:12.5px">${esc(themeName(d, c.theme))}</span>
          <dl>
            <dt>Puntuación</dt><dd>${num(c.score, 0)}</dd>
            <dt>Cierre</dt><dd>${price(c.close, c.currency)}</dd>
            <dt>Pivote</dt><dd>${price(c.pivot, c.currency)}</dd>
            <dt>Invalidación</dt><dd>${price(c.inv, c.currency)}</dd>
            <dt>Riesgo</dt><dd class="risk-${esc(c.risk)}">${esc(c.risk)}</dd>
          </dl>
        </article>`).join("")}</div>` : `<p class="empty">Hoy ninguna candidata cumple los filtros de prioridad. No hay que forzar operaciones.</p>`}`;
  }

  const themeName = (d, k) => (d.themes.find((t) => t.key === k) || {}).name || k;

  // Acciones líderes de una temática: las de mayor fuerza relativa, estén o no en una ruptura.
  function leadersHTML(t) {
    const top = t.top || [];
    if (!top.length) return `<p class="leaders empty">Sin datos de líderes en esta publicación.</p>`;
    return `<div class="leaders">
      <p class="cap">Las ${top.length} acciones con más fuerza relativa de la temática (de ${t.n} valores líquidos). Pulsa una para abrir su ficha.</p>
      <div class="tbl-wrap"><table class="lt">
        <thead><tr><th class="left">Valor</th><th title="Percentil de fuerza relativa en todo el universo líquido">RS</th><th>1 m</th><th>3 m</th><th>6 m</th>
          <th>Desde máx. 52s</th><th class="left">Estado</th><th>Punt.</th></tr></thead>
        <tbody>${top.map((x) => `<tr data-sym="${esc(x.sym)}" tabindex="0">
          <td class="tk-cell"><a href="#valor=${encodeURIComponent(x.sym)}">${esc(x.sym)}</a><small>${esc(x.name && x.name !== x.sym ? x.name : "")}</small></td>
          <td><strong>${num((x.rs_pct || 0) * 100, 0)}</strong></td>
          <td class="${cls(x.r1m)}">${pct(x.r1m, 0)}</td><td class="${cls(x.r3m)}">${pct(x.r3m, 0)}</td><td class="${cls(x.r6m)}">${pct(x.r6m, 0)}</td>
          <td class="${x.dhi >= -0.05 ? "pos" : ""}">${pct(x.dhi, 1)}</td>
          <td class="left">${x.state ? chip(x.state) : "—"}${x.watch ? ` <span class="wl-tag" title="Está en la watchlist de hoy">watchlist</span>` : ""}</td>
          <td>${isNum(x.score) ? num(x.score, 0) : "—"}</td></tr>`).join("")}</tbody>
      </table></div></div>`;
  }

  function renderThemes(d, hist) {
    const W = d.theme_weights || { rs: 45, consistency: 15, breadth: 20, highs: 10, volume: 10 };
    const comps = [["rs", "Fuerza relativa", 1], ["consistency", "Consistencia", 0.78], ["breadth", "Amplitud", 0.58],
      ["highs", "Cerca de máximos", 0.42], ["volume", "Volumen", 0.28]].map(([k, n, op]) => [k, n, W[k] || 0, op]);
    const VISIBLE = 12;
    const rows = d.themes.map((t, i) => {
      const s = t.score;
      const segs = comps.map(([k, , max, op]) => s[k] === null || s[k] === undefined
        ? `<span class="na" style="width:${max}%" title="Catalizador no disponible: sus puntos se redistribuyen"></span>`
        : `<span style="width:${s[k]}%;background:var(--pivot);opacity:${op}" title="${esc(k)}: ${num(s[k], 1)} de ${max}"></span>`).join("");
      const h = hist.map((x) => x.themes && x.themes[t.key]);
      return `<details class="theme" data-key="${esc(t.key)}"><summary title="Ver las acciones líderes de ${esc(t.name)}">
        <div class="theme-row ${t.selected ? "sel" : ""}">
        <span class="rk">${i + 1}</span>
        <span class="tn">${esc(t.name)} <span class="chev" aria-hidden="true"></span><small>${esc(t.status)}${t.forced ? " · incluida a mano" : ""}${t.biased ? " · amplitud con muestra sesgada" : ""}</small></span>
        <span class="sc">${num(s.total, 0)}</span>
        <span class="bar" role="img" aria-label="Componentes de la puntuación">${segs}</span>
        <span class="meta">RS 1m/3m/6m ${pct(t.rs1, 0)} / ${pct(t.rs3, 0)} / ${pct(t.rs6, 0)} · ${num(t.p50 * 100, 0)}% sobre SMA50 ${spark(h, 60, 18)}
          <br>${num(t.near_hi * 100, 0)}% cerca de máximos · posición RS ${num((t.rs_rank ?? 0) * 100, 0)}/100</span>
      </div></summary>${leadersHTML(t)}</details>`;
    });
    const shown = rows.slice(0, VISIBLE).join("");
    const rest = rows.slice(VISIBLE);
    $("#tematicas").innerHTML = `<h2>Temáticas</h2>
      <p class="lead">Ordenadas por puntuación 0-100. Las marcadas con barra azul a la izquierda son las seleccionadas para buscar acciones. Pulsa una temática para ver sus acciones líderes.</p>
      <div class="themes">${shown}</div>
      ${rest.length ? `<details class="more"><summary>Ver las ${rest.length} temáticas restantes</summary><div class="themes">${rest.join("")}</div></details>` : ""}
      <p class="legend">${comps.map(([, n, max, op]) => `<span><i style="background:var(--pivot);opacity:${op}"></i>${n} (${max})</span>`).join("")}</p>`;
  }

  function bindLeaders() {
    const open = (tr) => { location.hash = `valor=${encodeURIComponent(tr.dataset.sym)}`; };
    $("#tematicas").addEventListener("click", (e) => {
      const tr = e.target.closest(".lt tr[data-sym]");
      if (tr && !e.target.closest("a")) open(tr);
    });
    $("#tematicas").addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches(".lt tr[data-sym]")) { e.preventDefault(); open(e.target); }
    });
  }

  // ---------- ficha de un valor (fila desplegada de la watchlist y buscador) ----------
  function detailHTML(c) {
    const comp = c.components || {};
    const h = SCORE_HIST[c.sym] || [];
    const live = !!c.live;
    const catTxt = c.catalyst ? (c.catalyst_source ? `<a href="${esc(c.catalyst_source)}" target="_blank" rel="noopener">${esc(c.catalyst)}</a>` : esc(c.catalyst))
      : live || comp.catalyst == null ? "no evaluado (su peso se redistribuye)" : "sin catalizador verificado";
    return `<div class="chart-box"><div class="chart" role="img" aria-label="Gráfico diario de ${esc(c.sym)} con nivel de ruptura, borde de la consolidación, invalidación y medias móviles"><p class="empty">Cargando gráfico…</p></div>
        ${chartLegend(c)}</div>
      <div class="detail-grid">
        <div><h3>Niveles</h3><dl>
          <dt>Nivel de ruptura</dt><dd>${price(c.pivot, c.currency)}${c.level_kind ? `<br><span class="dim">${esc(LEVEL_KIND[c.level_kind] || c.level_kind)}</span>` : ""}</dd>
          <dt>Distancia</dt><dd>${pct(c.dist)} · ${num((c.close - c.pivot) / c.atr, 1)} ATR</dd>
          <dt>Máximo de la base</dt><dd>${price(isNum(c.peak) ? c.peak : c.pivot, c.currency)} (${dateEs(c.pivot_date)})${c.touch_date && c.peak > c.pivot * 1.02 ? `<br><span class="dim">línea por el máximo del ${dateEs(c.touch_date)}</span>` : ""}</dd>
          <dt>Invalidación</dt><dd>${isNum(c.inv) ? `${price(c.inv, c.currency)} (${pct(c.inv_pct)}; ${num(c.inv_atr, 1)} ATR)` : "—"}</dd>
          <dt>ATR 14</dt><dd>${price(c.atr, c.currency)} (${pct(c.atr_pct, 1, false)})</dd>
          <dt>Volumen sesión / media 20s</dt><dd>${num(c.vol / 1e6, 2)} M / ${num(c.v20 / 1e6, 2)} M</dd>
          <dt>Base</dt><dd>${c.base_len} sesiones, profundidad ${pct(c.depth, 0, false)}</dd>
          <dt>Desde máx. 52s</dt><dd>${pct(c.dhi)}</dd>
        </dl></div>
        <div><h3>Hipótesis</h3>
          ${c.confirm ? `<p><strong>Confirmaría:</strong> ${esc(c.confirm)}</p>` : ""}
          ${c.invalidate ? `<p><strong>Invalidaría:</strong> ${esc(c.invalidate)}</p>` : ""}
          ${c.why ? `<p class="dim">${esc(c.why)}</p>` : ""}
          <p><strong>Catalizador:</strong> ${catTxt}</p>
          <p><strong>Resultados:</strong> ${c.next_earnings ? dateEs(c.next_earnings, true) + (c.next_earnings_est ? " (estimada)" : "") : live || !c.theme ? "no consultados" : "sin fecha publicada"}</p>
          <p><a href="${tvUrl(c.sym)}" target="_blank" rel="noopener">Abrir gráfico en TradingView</a> · <a href="${yfUrl(c.sym)}" target="_blank" rel="noopener">Yahoo Finance</a></p>
        </div>
        <div><h3>Puntuación ${num(c.score, 1)}</h3><dl>
          <dt>Fuerza relativa (25)</dt><dd>${num(comp.rs, 1)} · percentil ${num((c.rs_pct || 0) * 100, 0)}</dd>
          <dt>Base y estructura (25)</dt><dd>${num(comp.base, 0)}</dd>
          <dt>Ruptura y volumen (20)</dt><dd>${num(comp.breakout, 0)}</dd>
          <dt>Tendencia (15)</dt><dd>${num(comp.trend, 0)}</dd>
          <dt>Liquidez (10)</dt><dd>${num(comp.liquidity, 0)} · ${num((c.mdv_usd || 0) / 1e6, 0)} M USD/día</dd>
          <dt>Catalizador (5)</dt><dd>${comp.catalyst == null ? "sin datos (redistribuido)" : num(comp.catalyst, 0)}</dd>
          <dt>Capitalización</dt><dd>${isNum(c.mcap_usd) ? num(c.mcap_usd / 1e9, 1) + " B USD" : "no verificada"}</dd>
          <dt>Riesgo</dt><dd class="risk-${esc(c.risk)}">${esc(c.risk)} (${c.risk_points} punto${c.risk_points === 1 ? "" : "s"})</dd>
          ${h.length > 1 ? `<dt>Histórico</dt><dd>${spark(h, 120, 24)}</dd>` : ""}
        </dl></div>
      </div>
      ${c.qm ? qmBlock(c) : ""}`;
  }

  function mountDetail(root, c, kPromise) {
    const el = root.querySelector(".chart");
    drawChart(el, c, kPromise);
    qmCalc(root.querySelector(".qm-box"), c);
    const box = root.querySelector(".sma200");
    if (box) box.addEventListener("change", () => {
      store.set("radar.sma200", box.checked);
      if (el._sma && el._sma[200]) el._sma[200].applyOptions({ visible: box.checked });
    });
  }

  function renderWatchlist(d, byS, scoreHist) {
    const pres = d.lists.presented.map((s) => byS[s]).filter(Boolean);
    pres.forEach((c) => { c.qm_verdict = c.qm ? { "Cumple": 0, "Con reservas": 1, "No cumple": 2 }[c.qm.verdict] : 3; });
    const f = Object.assign({ theme: "", state: "", risk: "", ds: "", qm: "", q: "" }, store.get("radar.filters", {}));
    const sort = store.get("radar.sort", { key: "score", dir: -1 });
    const themes = [...new Set(pres.map((c) => c.theme))];
    const opt = (v, label, cur) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`;
    $("#watchlist").innerHTML = `<h2>Watchlist</h2>
      <p class="lead">Las 5 mejores estructuras de cada temática seleccionada. La regla muestra la invalidación (marca roja), el nivel de ruptura (línea azul) y el cierre (punto). Pulsa una fila para ver niveles y condiciones.</p>
      <div class="filters">
        <label>Temática<select id="f-theme">${opt("", "Todas", f.theme)}${themes.map((t) => opt(t, themeName(d, t), f.theme)).join("")}</select></label>
        <label>Estado<select id="f-state">${opt("", "Todos", f.state)}${STATE_ORDER.map((s) => opt(s, STATE_LABEL[s], f.state)).join("")}</select></label>
        <label>Riesgo<select id="f-risk">${opt("", "Todos", f.risk)}${["Bajo", "Medio", "Alto"].map((s) => opt(s, s, f.risk)).join("")}</select></label>
        <label>Cambio vs. sesión anterior<select id="f-ds">${opt("", "Todos", f.ds)}${Object.entries(DS_LABEL).map(([k, v]) => opt(k, v, f.ds)).join("")}</select></label>
        <label>Qullamaggie<select id="f-qm">${opt("", "Todas", f.qm)}${["Cumple", "Con reservas", "No cumple"].map((s) => opt(s, s, f.qm)).join("")}</select></label>
        <label>Filtrar<input id="f-q" type="search" placeholder="Ticker o empresa" value="${esc(f.q)}"></label>
        <span class="count" id="wl-count"></span>
      </div>
      <div class="tbl-wrap"><table id="wl">
        <thead><tr>
          <th class="left" data-sort="sym">Valor</th><th class="left" data-sort="theme">Temática</th><th data-sort="score">Punt.</th>
          <th class="left" data-sort="state">Estado</th><th class="left">Regla</th><th data-sort="close">Cierre</th><th data-sort="live_dist" title="Último precio de Yahoo Finance, actualizado cada minuto mientras la web está abierta (ordena por distancia al nivel de ruptura)">Ahora</th>
          <th data-sort="dist">vs nivel</th><th data-sort="inv_pct">Invalidación</th><th data-sort="rvol">Vol. rel.</th>
          <th data-sort="next_earnings">Resultados</th><th data-sort="risk_points">Riesgo</th><th class="left" data-sort="qm_verdict">Qullamaggie</th><th class="left" data-sort="daily_status">Hoy</th>
        </tr></thead><tbody></tbody></table></div>`;

    const tbody = $("#wl tbody");
    const draw = () => {
      let rows = pres.filter((c) => (!f.theme || c.theme === f.theme) && (!f.state || c.state === f.state)
        && (!f.risk || c.risk === f.risk) && (!f.ds || c.daily_status === f.ds) && (!f.qm || (c.qm && c.qm.verdict === f.qm))
        && (!f.q || (c.sym + " " + c.name).toLowerCase().includes(f.q.toLowerCase())));
      rows.sort((a, b) => {
        const va = a[sort.key], vb = b[sort.key];
        if (va === vb) return b.score - a.score;
        if (va === null || va === undefined) return 1;
        if (vb === null || vb === undefined) return -1;
        return (va > vb ? 1 : -1) * sort.dir;
      });
      document.querySelectorAll("#wl th[data-sort]").forEach((th) => th.setAttribute("aria-sort", th.dataset.sort === sort.key ? (sort.dir > 0 ? "ascending" : "descending") : "none"));
      $("#wl-count").textContent = `${rows.length} de ${pres.length} candidatas`;
      tbody.innerHTML = rows.length ? rows.map((c) => `
        <tr class="row ${stClass(c.state)}" data-sym="${esc(c.sym)}" tabindex="0" aria-expanded="false">
          <td class="tk-cell">${esc(c.sym)}<small>${esc(c.name)}</small></td>
          <td class="left dim th-cell" title="${esc(themeName(d, c.theme))}">${esc(themeName(d, c.theme))}</td>
          <td><strong>${num(c.score, 0)}</strong></td>
          <td class="left">${chip(c.state)}</td>
          <td class="left">${ladder(c)}</td>
          <td>${price(c.close, c.currency)} <span class="dim">${esc(c.currency)}</span></td>
          <td class="live-cell" data-live="${esc(c.sym)}">${liveCell(c)}</td>
          <td class="${cls(c.dist)}">${pct(c.dist)}</td>
          <td title="${esc(pct(c.inv_pct))} desde el cierre">${price(c.inv, c.currency)}</td>
          <td>${num(c.rvol, 2)}x</td>
          <td>${c.next_earnings ? dateEs(c.next_earnings) + (c.next_earnings_est ? " (est.)" : "") : "—"}</td>
          <td class="risk-${esc(c.risk)}">${esc(c.risk)}</td>
          <td class="left">${c.qm ? `<span class="qmv qmv-${esc(c.qm.verdict.replace(/\s+/g, "-"))}">${esc(c.qm.verdict)}</span>` : "—"}</td>
          <td class="left ds ds-${esc(c.daily_status)}">${esc(DS_LABEL[c.daily_status] || c.daily_status || "")}${isNum(c.score_prev) ? ` <span class="dim">(${num(c.score_prev, 0)})</span>` : ""}</td>
        </tr>`).join("") : `<tr><td colspan="14" class="empty">Ninguna candidata cumple los filtros. Prueba a quitar alguno.</td></tr>`;
    };
    const toggle = (tr) => {
      const open = tr.getAttribute("aria-expanded") === "true";
      if (open) {
        const det = tr.nextElementSibling;
        if (det && det.classList.contains("detail")) { const ch = det.querySelector(".chart"); ch && (ch._disposeAll || ch._dispose || (() => {}))(); det.remove(); }
        tr.setAttribute("aria-expanded", "false"); return;
      }
      const c = byS[tr.dataset.sym];
      tr.insertAdjacentHTML("afterend", `<tr class="detail"><td colspan="14"><div class="detail-inner">${detailHTML(c)}</div></td></tr>`);
      tr.setAttribute("aria-expanded", "true");
      // La tabla puede ser más ancha que la pantalla: la ficha se ajusta al ancho visible.
      const inner = tr.nextElementSibling.querySelector(".detail-inner"), wrap = tr.closest(".tbl-wrap");
      const fit = () => { inner.style.width = `${Math.max(280, wrap.clientWidth - 22)}px`; };
      fit();
      const ro = new ResizeObserver(fit); ro.observe(wrap);
      const ch = inner.querySelector(".chart"); const prevDispose = () => ch._dispose && ch._dispose();
      ch._disposeAll = () => { ro.disconnect(); prevDispose(); };
      mountDetail(tr.nextElementSibling, c, loadTicker(c.sym).then((x) => x.k));
    };
    tbody.addEventListener("click", (e) => { const tr = e.target.closest("tr.row"); if (tr && !e.target.closest("a")) toggle(tr); });
    tbody.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr.row")) { e.preventDefault(); toggle(e.target); } });
    const bind = (id, key) => $(id).addEventListener("input", (e) => { f[key] = e.target.value; store.set("radar.filters", f); draw(); });
    bind("#f-theme", "theme"); bind("#f-state", "state"); bind("#f-risk", "risk"); bind("#f-ds", "ds"); bind("#f-qm", "qm"); bind("#f-q", "q");
    document.querySelectorAll("#wl th[data-sort]").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.sort; sort.dir = sort.key === k ? -sort.dir : (["sym", "theme", "state", "next_earnings", "daily_status"].includes(k) ? 1 : -1); sort.key = k;
      store.set("radar.sort", sort); draw();
    }));
    draw();
  }

  // Escáner Qullamaggie: todo el universo, rupturas que cumplen los requisitos obligatorios.
  let QMS = {};
  function renderQM(d) {
    const rows = d.lists.qm_setups || [];
    QMS = Object.fromEntries(rows.map((x) => [x.sym, x]));
    const m = d.qm_market || {};
    $("#qullamaggie").innerHTML = `<h2>Setups Qullamaggie</h2>
      <p class="lead">Escáner de todo el universo, no solo de las temáticas: valores entre el 2% que más sube a 1, 3 o 6 meses, con ADR ≥ 5%, subida previa ≥ 30%, consolidación de 2 semanas a 2 meses y retroceso ordenado, que hoy rompen o están a ≤ 5% del nivel de ruptura. "Con reservas": falla alguna regla secundaria${m.light && m.light !== "verde" ? " o el filtro de mercado no está en verde (hoy: " + esc(m.light) + ")" : ""}.</p>
      ${rows.length ? `<div class="tbl-wrap"><table class="lt qm-table">
        <thead><tr><th class="left">Valor</th><th class="left">Estado</th><th>Nivel de ruptura</th><th>Distancia</th><th>Ahora</th>
          <th>ADR</th><th>Subida previa</th><th>Base</th><th class="left">Veredicto</th></tr></thead>
        <tbody>${rows.map((x) => `<tr data-sym="${esc(x.sym)}" tabindex="0">
          <td class="tk-cell"><a href="#valor=${encodeURIComponent(x.sym)}">${esc(x.sym)}</a><small>${esc(x.name && x.name !== x.sym ? x.name : "")}${x.theme ? " · " + esc(themeName(d, x.theme)) : ""}</small></td>
          <td class="left">${chip(x.state)}${x.presented ? ` <span class="wl-tag" title="Está en la watchlist de hoy">watchlist</span>` : ""}</td>
          <td>${price(x.pivot, x.currency)}<small class="dim block">${esc(LEVEL_KIND[x.level_kind] || "")}</small></td>
          <td class="${cls(x.dist)}">${pct(x.dist)}</td>
          <td class="live-cell" data-live="${esc(x.sym)}">${liveCell(x)}</td>
          <td>${pct(x.adr_pct, 1, false)}</td><td>${pct(x.prior_move, 0)}</td><td>${x.base_len} ses.</td>
          <td class="left"><span class="qmv qmv-${esc(x.qm.verdict.replace(/\s+/g, "-"))}">${esc(x.qm.verdict)}</span>${x.fails.length ? `<small class="dim block">falla: ${esc(x.fails.join("; ").toLowerCase())}</small>` : ""}</td>
        </tr>`).join("")}</tbody></table></div>` : `<p class="empty">Hoy ningún valor del universo cumple los requisitos obligatorios y está en ruptura o a punto. Es normal en mercados flojos: Qullamaggie espera.</p>`}`;
    const open = (tr) => { location.hash = `valor=${encodeURIComponent(tr.dataset.sym)}`; };
    $("#qullamaggie").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-sym]"); if (tr && !e.target.closest("a")) open(tr); });
    $("#qullamaggie").addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr[data-sym]")) { e.preventDefault(); open(e.target); }
    });
  }

  function renderAgenda(d, byS) {
    const cal = d.calendar || [];
    const groups = {};
    cal.forEach((e) => (groups[e.date] = groups[e.date] || []).push(e));
    const others = (d.lists.others || []).slice().sort((a, b) => b.score - a.score);
    const out = d.lists.outside || [];
    const elim = d.lists.eliminated || [];
    $("#agenda").innerHTML = `<h2>Agenda y descartes</h2>
      <p class="lead">Resultados próximos de las candidatas, valores que salen de la watchlist y rupturas confirmadas fuera de las temáticas seleccionadas.</p>
      <div class="cols">
        <div><h3>Resultados en los próximos 45 días</h3>
          ${cal.length ? `<ul class="plain">${Object.entries(groups).map(([dt, es]) => `<li><span class="when">${dateEs(dt, true)}</span> ${es.map((e) => esc(e.sym) + (e.est ? " (est.)" : "")).join(", ")}</li>`).join("")}</ul>` : `<p class="empty">Sin fechas publicadas.</p>`}
          ${d.lists.pending.length ? `<h3>Pendientes de reacción</h3><p>${d.lists.pending.map(esc).join(", ")}: publicaron tras el último cierre.</p>` : ""}
        </div>
        <div><h3>Extendidas, descartadas o fuera del top</h3>
          ${others.length ? `<ul class="plain">${others.slice(0, 25).map((o) => `<li>${chip(o.state)} <strong>${esc(o.sym)}</strong> <span class="dim">${esc(o.reason)}</span></li>`).join("")}</ul>` : `<p class="empty">Nada que señalar.</p>`}
          ${elim.length ? `<h3>Eliminadas respecto a la sesión anterior</h3><ul class="plain">${elim.map((e) => `<li><strong>${esc(e.sym)}</strong> <span class="dim">${esc(e.reason)}</span></li>`).join("")}</ul>` : ""}
        </div>
        <div>
          <h3>Rupturas confirmadas fuera de las temáticas</h3>
          ${out.length ? `<ul class="plain">${out.map((o) => `<li><a href="${tvUrl(o.sym)}" target="_blank" rel="noopener"><strong>${esc(o.sym)}</strong></a> <span class="dim">${esc(o.name)} · ${esc(themeName(d, o.theme) || "sin temática")} · ${pct(o.dist)} sobre el nivel · RS ${num(o.rs_pct * 100, 0)}</span></li>`).join("")}</ul>` : `<p class="empty">Ninguna con RS en el 20% superior.</p>`}
        </div>
      </div>`;
  }

  function renderMethod(d) {
    const cv = d.meta.coverage;
    const W = d.theme_weights || { rs: 45, consistency: 15, breadth: 20, highs: 10, volume: 10 };
    $("#metodo").innerHTML = `<h2>Método y limitaciones</h2>
      <div class="method">
        <p><strong>Datos.</strong> ${esc(d.meta.price_source)}. Solo cierres confirmados de la última sesión de cada mercado; nada en tiempo real. Universo: ${cv.universe.toLocaleString("es-ES")} valores (S&P 500/400/600, lista fija internacional y descubrimiento por mercado), ${cv.with_data.toLocaleString("es-ES")} con datos y ${cv.liquid.toLocaleString("es-ES")} líquidos (≥ 5 M USD diarios y precio ≥ 5 USD).</p>
        <p><strong>Temáticas.</strong> 0-100: fuerza relativa ${W.rs} (posición de la temática frente a las demás según la mediana de la RS compuesta de sus valores: 20% 1 mes, 40% 3 meses, 40% 6 meses, cada valor frente a su índice regional), consistencia ${W.consistency} (plazos de 1, 3 y 6 meses en los que la mediana supera a su índice), amplitud ${W.breadth} (% sobre SMA50 y SMA200, solo con valores de selección no sesgada), cerca de máximos ${W.highs} (% a menos de un 10% del máximo de 52 semanas) y volumen ${W.volume} (últimas 20 sesiones frente a las 50 anteriores, valores y ETF del sector).</p>
        <p><strong>Estados.</strong> La consolidación empieza en el máximo de las últimas 60 sesiones con al menos 5 de antigüedad (si un cierre posterior lo superó, la base ya está rota). Su borde superior es la línea más plana que parte de ese máximo y deja por debajo los máximos posteriores: plana en un canal, descendente en triángulos y flags; la descendente solo vale si la base tocó su suelo en sus dos primeros tercios (en un rebote en V manda el máximo). El nivel de ruptura es esa línea proyectada al día, o el máximo de las 3 sesiones anteriores si queda por encima. Confirmada: cierre sobre el nivel con volumen ≥ 1,5x la media de 20 sesiones y en la mitad alta del día. Temprana: cruza sin volumen o sin continuidad. Pre-breakout: a ≤ 5% del nivel con base de al menos 10 sesiones (o flag de 5-9 y ≤ 12% de profundidad). Retest: volvió al nivel tras cruzarlo. Extendida: > 10% sobre el nivel o > 3 ATR sobre la SMA20.</p>
        <p><strong>Puntuación de acciones.</strong> Fuerza relativa 25, base y estructura 25, ruptura y volumen 20, tendencia diaria y semanal 15, liquidez 10, catalizador 5. Es una clasificación, no una probabilidad. El riesgo se etiqueta aparte: volatilidad, resultados próximos, distancia a la invalidación y liquidez.</p>
        <p><strong>Qullamaggie (solo rupturas).</strong> Reglas de su artículo "3 timeless setups", con umbrales objetivos. Obligatorias: estar entre el 2% que más sube a 1, 3 o 6 meses, ADR ≥ 5%, subida previa ≥ 30% en 1-3 meses, consolidación de 2 semanas a 2 meses (flag desde 5 sesiones) y retroceso ordenado (≤ 50% de la subida). Secundarias: mínimos crecientes (el último tercio de la base sobre su mínimo), rango que se estrecha (últimas 5 sesiones ≤ 50% del rango de la base) y precio surfeando las SMA10/SMA20 (o SMA50) ascendentes. Entrada en el máximo de la primera vela de 1, 5 o 60 minutos; stop en el mínimo del día y nunca más ancho que el ADR; venta de 1/3-1/2 a los 3-5 días, stop a la entrada y el resto al primer cierre bajo la SMA10 o SMA20. Posición habitual 10-20%, nunca más del 30%. Filtro de mercado: Nasdaq 100 frente a sus SMA10 y SMA20. Son niveles orientativos para estudiar el gráfico, no órdenes ni recomendaciones.</p>
        <p><strong>Gráficos y buscador.</strong> Velas diarias con las medias de 10, 20 y 50 sesiones que usa Qullamaggie (la de 200, opcional). El buscador de la cabecera abre la ficha de cualquier valor del universo diario${d.web && d.web.worker_url ? " y, para el resto del mercado, la calcula al momento en el navegador con los mismos umbrales a partir de los datos de Yahoo Finance (sin temática, catalizador ni fechas de resultados)" : ""}.</p>
        <p><strong>Límites.</strong> Los niveles son algorítmicos y deben validarse en el gráfico. La amplitud solo se mide en EE. UU. Las fechas de resultados "est." no están confirmadas por la empresa. Ninguna fila es una recomendación de inversión.</p>
      </div>`;
    $("#foot").innerHTML = `Generado ${esc(d.meta.generated_local.replace("T", " "))} · versión ${esc(d.meta.version)} · <a href="data/latest.json">datos en JSON</a> · gráficos con <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noopener">TradingView Lightweight Charts</a>`;
  }

  // ---------- buscador: cualquier valor ----------
  // 1) Universo diario (≈ 2.700 valores ya calculados por el motor).
  // 2) Si hay Worker configurado, cualquier ticker de Yahoo Finance, calculado al momento en el
  //    navegador con docs/engine.js (mismas reglas y umbrales que el motor diario).
  let indexPromise = null;
  const loadIndex = () => indexPromise || (indexPromise = getJSON("data/universe.json").then((u) => {
    const rows = u.rows || [];
    return { rows, map: new Map(rows.map((r) => [r[0], r])) };
  }).catch((e) => { indexPromise = null; throw e; }));
  const workerUrl = () => ((D && D.web && D.web.worker_url) || "").replace(/\/+$/, "");

  async function getWorker(path) {
    const r = await fetch(workerUrl() + path);  // petición simple: sin cabeceras que obliguen a preflight
    let body = null;
    try { body = await r.json(); } catch { /* sin cuerpo */ }
    if (!r.ok) {
      const e = new Error((body && body.error) || `el servicio respondió ${r.status}`);
      e.status = r.status; throw e;
    }
    return body;
  }

  function suggest(q, idx) {
    const Q = q.trim().toUpperCase(), ql = q.trim().toLowerCase();
    if (!Q) return [];
    const out = [];
    for (const r of idx.rows) {
      const sym = r[0], name = (r[1] || "").toLowerCase();
      const rank = sym === Q ? 0 : sym.startsWith(Q) ? 1 : name.startsWith(ql) ? 2 : name.includes(ql) ? 3 : sym.includes(Q) ? 4 : -1;
      if (rank >= 0) out.push({ rank, sym, name: r[1], theme: r[2], state: r[3], score: r[4] });
    }
    out.sort((a, b) => a.rank - b.rank || b.score - a.score);
    return out.slice(0, 8);
  }

  function initFinder() {
    const input = $("#q"), list = $("#q-list");
    let items = [], active = -1, seq = 0, timer = null;
    const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); active = -1; };
    const paint = (hint) => {
      list.innerHTML = items.map((it, i) => `<li role="option" id="q-opt-${i}" data-sym="${esc(it.sym)}" aria-selected="${i === active}">
          <span class="s">${esc(it.sym)}</span><span class="n">${esc(it.name || "")}</span>
          <span class="g">${it.live ? "se calcula al momento" : `${esc(STATE_LABEL[it.state] || it.state)} · ${num(it.score, 0)}`}</span></li>`).join("")
        + (hint ? `<li class="hint" role="presentation">${hint}</li>` : "");
      list.hidden = !items.length && !hint;
      input.setAttribute("aria-expanded", String(!list.hidden));
      if (active >= 0) input.setAttribute("aria-activedescendant", `q-opt-${active}`); else input.removeAttribute("aria-activedescendant");
    };
    const pick = (sym) => { close(); input.value = ""; input.blur(); openTicker(sym); };
    const update = async () => {
      const q = input.value, my = ++seq;
      if (!q.trim()) { items = []; close(); return; }
      let idx = null;
      try { idx = await loadIndex(); } catch { /* sin índice: solo el Worker */ }
      if (my !== seq) return;
      items = idx ? suggest(q, idx) : [];
      active = items.length ? 0 : -1;
      const enterHint = `Pulsa Intro para abrir <strong>${esc(q.trim().toUpperCase())}</strong>`;
      paint(items.length ? "" : workerUrl() ? enterHint : "No está en el universo del radar de hoy.");
      clearTimeout(timer);
      if (workerUrl() && q.trim().length >= 2) {
        timer = setTimeout(async () => {
          try {
            const res = await getWorker(`/search?q=${encodeURIComponent(q.trim())}`);
            if (my !== seq) return;
            const have = new Set(items.map((x) => x.sym));
            for (const r of res || []) {
              if (items.length >= 10) break;
              if (have.has(r.symbol)) continue;
              const inIdx = idx && idx.map.get(r.symbol);
              items.push(inIdx ? { sym: r.symbol, name: inIdx[1], state: inIdx[3], score: inIdx[4] }
                : { sym: r.symbol, name: `${r.name || ""}${r.exchange ? " · " + r.exchange : ""}`, live: true });
            }
            if (active < 0 && items.length) active = 0;
            paint(items.length ? "" : enterHint);
          } catch { /* el buscador del Worker es opcional */ }
        }, 300);
      }
    };
    input.addEventListener("input", update);
    input.addEventListener("focus", () => { loadIndex().catch(() => {}); if (input.value.trim()) update(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!items.length) return;
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        paint(""); list.querySelector(`#q-opt-${active}`)?.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        const q = input.value.trim().toUpperCase();
        if (!q) return;
        pick(active >= 0 && items[active] ? items[active].sym : q);
      } else if (e.key === "Escape") { close(); }
    });
    list.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-sym]"); if (li) { e.preventDefault(); pick(li.dataset.sym); } });
    document.addEventListener("click", (e) => { if (!e.target.closest(".finder")) close(); });
  }

  const benchName = (sym) => ((D.regime.indices || []).find((i) => i.sym === sym) || {}).name || sym;

  let currentSym = null;
  const tickerFromHash = () => { const m = location.hash.match(/^#valor=(.+)$/); return m ? decodeURIComponent(m[1]).toUpperCase() : null; };

  async function openTicker(raw, { push = true } = {}) {
    const sym = String(raw || "").trim().toUpperCase();
    if (!sym) return;
    currentSym = sym;
    const sec = $("#ficha");
    const old = sec.querySelector(".chart");
    if (old && old._dispose) old._dispose();
    sec.hidden = false;
    sec.innerHTML = `<p class="empty">Buscando ${esc(sym)}…</p>`;
    // Desplaza hasta la ficha sin que la cabecera fija tape el ticker.
    const bar = $(".top"), sticky = getComputedStyle(bar).position === "sticky";
    window.scrollTo({ top: sec.getBoundingClientRect().top + window.scrollY - (sticky ? bar.offsetHeight + 8 : 8),
      behavior: reducedMotion() ? "auto" : "smooth" });
    const url = `${location.pathname}${location.search}#valor=${encodeURIComponent(sym)}`;
    if (push && tickerFromHash() !== sym) history.pushState({ valor: sym }, "", url);
    else history.replaceState({ valor: sym }, "", url);
    try {
      let idx = null;
      try { idx = await loadIndex(); } catch { /* sin índice */ }
      let c, kPromise, note;
      if (idx && idx.map.has(sym)) {
        const x = await loadTicker(sym);
        c = BYS[sym] || x.rec;
        kPromise = Promise.resolve(x.k);
        const where = c.theme ? `Temática: ${themeName(D, c.theme)}.` : "Sin temática asignada.";
        if (c.presented) note = `En la watchlist de hoy. ${where} Datos del cierre del ${dateEs(c.date)}.`;
        else {
          const why = c.liquid === false ? "liquidez por debajo del mínimo del radar"
            : !STATE_ORDER.includes(c.state) ? `estado ${STATE_LABEL[c.state] || c.state}${c.why ? " (" + c.why + ")" : ""}`
              : D.selected_themes.includes(c.theme) ? "por debajo de las 5 mejores de su temática" : "su temática no está seleccionada hoy";
          note = `${where} No está en la watchlist: ${why}. Datos del cierre del ${dateEs(c.date)}${BYS[sym] ? "" : "; sin catalizador ni fechas de resultados (su peso se redistribuye)"}.`;
        }
      } else if (workerUrl()) {
        let rawK;
        try { rawK = await getWorker(`/chart?symbol=${encodeURIComponent(sym)}`); } catch (e) {
          throw new Error(e.status === 404 || e.status === 400
            ? `Yahoo Finance no tiene datos de ${sym}. Revisa el ticker: fuera de EE. UU. lleva el sufijo de su bolsa (SAP.DE, 7203.T, AZN.L…)`
            : `No se pudo consultar ${sym} (${e.message})`);
        }
        const E = window.RadarEngine;
        const { series, partial } = E.prepareSeries(rawK, Date.now() / 1000);
        const ctx = { ...D.engine, fx: { ...D.engine.fx } };
        const cur = E.currencyOf(series.symbol, series.meta, ctx.settings);
        const need = E.fxNeed(cur, ctx.fx);
        let fxNote = "";
        if (need) {
          try {
            const fxk = await getWorker(`/chart?symbol=${encodeURIComponent(need.pair)}`);
            const last = fxk.c[fxk.c.length - 1];
            if (isNum(last) && last > 0) ctx.fx[need.base] = last; else throw new Error("sin cotización");
          } catch { fxNote = ` No se pudo convertir ${cur} a USD: la liquidez no se puede evaluar.`; }
        }
        c = E.evaluateTicker(series, ctx);
        if (!c) throw new Error(`${sym} tiene menos de 130 sesiones de historial: no se puede evaluar con las reglas del radar`);
        kPromise = Promise.resolve(series);
        note = `Calculado ahora con datos de Yahoo Finance hasta el cierre del ${dateEs(c.date)}${partial ? " (la sesión de hoy sigue abierta: se usa el último cierre)" : ""}. ` +
          `Fuera del universo diario: sin temática, catalizador ni fechas de resultados. Fuerza relativa frente al ${benchName(c.benchmark)}, en percentil del universo líquido del radar.${fxNote}`;
      } else {
        sec.innerHTML = `<div class="ficha-head"><div><h2 class="ficha-tk">${esc(sym)}</h2>
          <p class="ficha-note">No está en el universo del radar de hoy. Para calcular cualquier ticker al momento hay que activar el servicio de búsqueda (Worker de Cloudflare, instrucciones en el README del repositorio).</p></div>
          <button type="button" class="close">Cerrar</button></div>`;
        sec.querySelector(".close").addEventListener("click", closeTicker);
        return;
      }
      const qv = c.qm ? `<span class="qmv qmv-${esc(c.qm.verdict.replace(/\s+/g, "-"))}">Qullamaggie: ${esc(c.qm.verdict)}</span>` : "";
      sec.innerHTML = `<div class="ficha-head">
          <div>
            <h2 class="ficha-tk">${esc(c.sym)} <small>${esc(c.name && c.name !== c.sym ? c.name : "")}</small></h2>
            <p class="ficha-meta">${chip(c.state)}<span>Puntuación <strong>${num(c.score, 0)}</strong></span>
              <span>Cierre <strong>${price(c.close, c.currency)}</strong> <span class="dim">${esc(c.currency)}</span> <span class="${cls(c.d1)}">${pct(c.d1)}</span></span>
              <span class="risk-${esc(c.risk)}">Riesgo ${esc((c.risk || "").toLowerCase())}</span>${qv}</p>
            <p class="ficha-live" data-live-ficha></p>
            <p class="ficha-note">${esc(note)}</p>
          </div>
          <button type="button" class="close">Cerrar</button>
        </div>
        <div class="ficha-body">${detailHTML(c)}</div>`;
      sec.querySelector(".close").addEventListener("click", closeTicker);
      mountDetail(sec, c, kPromise);
      LIVE.ficha = c;
      if (LIVE.q[c.sym]) renderLive(); else liveTick();
    } catch (err) {
      sec.innerHTML = `<div class="ficha-head"><div><h2 class="ficha-tk">${esc(sym)}</h2><p class="ficha-note">${esc(err.message)}.</p></div>
        <button type="button" class="close">Cerrar</button></div>`;
      sec.querySelector(".close").addEventListener("click", closeTicker);
    }
  }

  // Cierra la ficha. `url`: quita el ticker de la dirección (sin crear otra entrada en el historial).
  function closeTicker({ focus = true, url = true } = {}) {
    const sec = $("#ficha");
    const ch = sec.querySelector(".chart");
    if (ch && ch._dispose) ch._dispose();
    sec.hidden = true; sec.innerHTML = "";
    currentSym = null; LIVE.ficha = null;
    if (url && tickerFromHash()) history.replaceState(null, "", location.pathname + location.search);
    if (focus) $("#q").focus();
  }

  // Inicio: cierra la ficha, limpia la dirección y vuelve arriba.
  function goHome(e) {
    if (e) e.preventDefault();
    if (currentSym || tickerFromHash()) {
      closeTicker({ focus: false, url: false });
      history.pushState(null, "", location.pathname + location.search);
    } else if (location.hash) {
      history.replaceState(null, "", location.pathname + location.search);
    }
    window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
  }

  // ---------- precios en vivo (Worker /quote, cada minuto con la web abierta) ----------
  // Los estados y puntuaciones son siempre los del cierre; aquí solo se compara el último precio
  // con los niveles (pivote, entrada, invalidación) y se proyecta el volumen del día.
  const LIVE = { q: {}, at: null, timer: null, error: "", ficha: null };
  const qDay = (q) => (q && q.time ? new Date((q.time + (q.gmtoffset || 0)) * 1000).toISOString().slice(0, 10) : null);
  const hhmm = (sec) => new Date(sec * 1000).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });

  function liveInfo(c) {
    const q = c && LIVE.q[c.sym];
    if (!q || !isNum(q.price)) return null;
    const day = qDay(q);
    if (!q.isOpen && !(day && c.date && day > c.date)) return { stale: true, q };
    const p = q.price;
    const chg = isNum(q.prevClose) && q.prevClose > 0 ? p / q.prevClose - 1 : null;
    const dist = p / c.pivot - 1;
    const trig = c.qm && isNum(c.qm.trigger) ? c.qm.trigger : null;
    let txt, kind;
    if (isNum(c.inv) && p < c.inv) { txt = "bajo la invalidación"; kind = "neg"; }
    else if (trig && p > trig) { txt = "supera la entrada"; kind = "hit"; }
    else if (p > c.pivot && c.close <= c.pivot) { txt = "rompe el nivel"; kind = "hit"; }
    else if (p > c.pivot) { txt = `${pct(dist)} sobre el nivel`; kind = "pos"; }
    else if (-dist < 0.001) { txt = "en el nivel"; kind = "near"; }
    else { txt = `a ${num(-dist * 100, 1)}% del nivel`; kind = "near"; }
    // Volumen relativo: con la sesión abierta, proyección al cierre con un perfil intradía
    // aproximado (se negocia más al principio): fracción de volumen ≈ fracción de tiempo ^ 0,8.
    let rv = null, proj = false;
    if (isNum(q.volume) && c.v20 > 0) {
      if (q.isOpen && q.start && q.end) {
        const t = Math.min(1, Math.max(0.03, (Date.now() / 1000 - q.start) / (q.end - q.start)));
        rv = q.volume / Math.pow(t, 0.8) / c.v20; proj = true;
      } else rv = q.volume / c.v20;
    }
    return { q, p, chg, dist, txt, kind, rv, proj, open: q.isOpen };
  }

  function liveCell(c) {
    const L = liveInfo(c);
    if (!L) return `<span class="dim">—</span>`;
    if (L.stale) return `<span class="dim" title="Sin cotizaciones nuevas desde el cierre que usa el radar">sin cambios</span>`;
    return `<span class="lp">${price(L.p, c.currency)}</span> <span class="${cls(L.chg)}">${pct(L.chg)}</span>
      <small class="ls-${L.kind}">${esc(L.txt)}${isNum(L.rv) ? ` · vol. ${L.proj ? "proy. " : ""}${num(L.rv, 1)}x` : ""}</small>`;
  }

  function fichaLive(c) {
    const L = liveInfo(c);
    if (!L) return "";
    if (L.stale) return `<span class="live-dot"></span><span class="dim">Sin cotizaciones nuevas desde el cierre del ${dateEs(c.date)}.</span>`;
    return `<span class="live-dot ${L.open ? "on" : ""}"></span><strong>${L.open ? "Ahora" : "Último cierre"} ${price(L.p, c.currency)}</strong>
      <span class="${cls(L.chg)}">${pct(L.chg)}</span> · <span class="ls-${L.kind}">${esc(L.txt)}</span>
      ${isNum(L.rv) ? ` · volumen ${L.proj ? "proyectado " : ""}${num(L.rv, 1)}x la media` : ""}
      <span class="dim"> · ${hhmm(L.q.time)}${L.open ? "" : ", mercado cerrado"}</span>`;
  }

  function updateLiveCharts() {
    document.querySelectorAll(".chart").forEach((el) => {
      const q = el._candles && LIVE.q[el._sym];
      const day = qDay(q);
      if (!q || !day || !isNum(q.price) || day < el._lastT || (day === el._lastT && !q.isOpen)) return;
      const o = isNum(q.open) && q.open > 0 ? q.open : q.price;
      try {
        el._candles.update({ time: day, open: o, high: Math.max(q.high || q.price, q.price, o), low: Math.min(q.low || q.price, q.price, o), close: q.price });
        if (el._vol && isNum(q.volume)) el._vol.update({ time: day, value: q.volume, color: alpha(q.price >= o ? el._col.up : el._col.down, 0.35) });
      } catch { /* vela fuera de orden: se ignora */ }
    });
  }

  function renderLive() {
    Object.values(BYS).forEach((c) => { const L = liveInfo(c); c.live_dist = L && !L.stale ? L.dist : null; });
    document.querySelectorAll("td[data-live]").forEach((td) => { const c = BYS[td.dataset.live] || QMS[td.dataset.live]; if (c) td.innerHTML = liveCell(c); });
    const f = document.querySelector("[data-live-ficha]");
    if (f && LIVE.ficha) f.innerHTML = fichaLive(LIVE.ficha);
    updateLiveCharts();
    const st = $("#live");
    if (!st) return;
    st.hidden = false;
    if (LIVE.error === "update") {
      st.innerHTML = `<span class="live-dot"></span>Precios en vivo: falta actualizar el Worker de Cloudflare (pega de nuevo cloudflare/worker.js)`;
      return;
    }
    if (LIVE.error) { st.innerHTML = `<span class="live-dot"></span>Precios en vivo no disponibles ahora; se reintenta en 5 minutos`; return; }
    const us = Object.entries(LIVE.q).find(([sym]) => !sym.includes("."));
    const open = !!(us && us[1].isOpen);
    st.innerHTML = `<span class="live-dot ${open ? "on" : ""}"></span>${open ? "Precios en vivo" : "Mercado de EE. UU. cerrado"} · actualizado ${hhmm(LIVE.at / 1000)}`;
  }

  async function liveTick() {
    clearTimeout(LIVE.timer);
    if (!workerUrl() || document.hidden || !D) return;
    const syms = [...new Set([...(D.lists.presented || []), ...(D.lists.qm_setups || []).map((x) => x.sym),
      ...(currentSym ? [currentSym] : [])])].sort();
    try {
      for (let i = 0; i < syms.length; i += 40) {
        const r = await getWorker(`/quote?symbols=${encodeURIComponent(syms.slice(i, i + 40).join(","))}`);
        if (!r || !r.quotes) throw Object.assign(new Error("Worker sin /quote"), { old: true });
        Object.assign(LIVE.q, r.quotes);
      }
      LIVE.error = ""; LIVE.at = Date.now();
    } catch (e) {
      LIVE.error = e.old ? "update" : "fail";
    }
    renderLive();
    if (LIVE.error === "update") return;
    const anyOpen = Object.values(LIVE.q).some((q) => q.isOpen);
    LIVE.timer = setTimeout(liveTick, !LIVE.error && anyOpen ? 60000 : 300000);
  }

  // ---------- arranque ----------
  async function main() {
    try {
      const d = await getJSON("data/latest.json");
      let hist = [];
      try {
        const idx = await getJSON("data/history/index.json");
        const lastN = idx.slice(-30);
        hist = (await Promise.all(lastN.map((x) => getJSON(`data/history/${x}.json`).catch(() => null)))).filter(Boolean);
      } catch { /* sin histórico todavía */ }
      const byS = Object.fromEntries(d.candidates.map((c) => [c.sym, c]));
      const scoreHist = {};
      hist.forEach((h) => Object.entries(h.watchlist || {}).forEach(([s, v]) => (scoreHist[s] = scoreHist[s] || []).push(v.score)));
      D = d; BYS = byS; SCORE_HIST = scoreHist;
      renderHeader(d);
      renderRegime(d, hist);
      renderPriority(d, byS);
      renderThemes(d, hist);
      bindLeaders();
      renderWatchlist(d, byS, scoreHist);
      renderQM(d);
      renderAgenda(d, byS);
      renderMethod(d);
      initFinder();
      // La dirección manda: #valor=XXX abre esa ficha; sin él, no hay ficha (botón Atrás incluido).
      const syncFromUrl = () => {
        const sym = tickerFromHash();
        if (sym && sym !== currentSym) openTicker(sym, { push: false });
        else if (!sym && currentSym) closeTicker({ focus: false, url: false });
      };
      window.addEventListener("popstate", syncFromUrl);
      window.addEventListener("hashchange", syncFromUrl);
      syncFromUrl();
      document.querySelectorAll("[data-home]").forEach((a) => a.addEventListener("click", goHome));
      if (workerUrl()) {
        liveTick();
        document.addEventListener("visibilitychange", () => { if (!document.hidden) liveTick(); });
      }
    } catch (err) {
      $("#app").innerHTML = `<div class="err"><strong>No se han podido cargar los datos.</strong> ${esc(err.message)}. Si es la primera vez, ejecuta el flujo "Radar diario" en la pestaña Actions del repositorio y recarga esta página cuando termine.</div>`;
      $("#session").textContent = "Sin datos";
    }
  }
  main();
})();
