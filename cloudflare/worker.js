/**
 * Radar de rupturas · intermediario para buscar cualquier ticker.
 *
 * El navegador no puede pedir datos a Yahoo Finance directamente (CORS). Este Worker de
 * Cloudflare (plan gratuito: 100.000 peticiones al día) hace la petición y devuelve solo lo
 * necesario, con permiso para que tu web lo lea. No guarda nada ni necesita claves.
 *
 *   GET /chart?symbol=AAPL         → velas diarias de 2 años + metadatos
 *   GET /search?q=apple            → sugerencias de tickers
 *   GET /quote?symbols=AAPL,MSFT   → último precio de hasta 40 valores (precios en vivo de la web)
 *   GET /pre?symbols=AAPL,MSFT     → pre-mercado de EE. UU. de hasta 40 valores: último precio, máximo y mínimo
 *   GET /prevol?symbols=AAPL,MSFT  → volumen del pre-mercado de hasta 40 valores (Nasdaq; Yahoo no lo publica)
 *
 * Despliegue: dash.cloudflare.com → Workers & Pages → Create → Worker → pega este archivo → Deploy.
 */

// Orígenes que pueden usar este Worker (tu web y pruebas en local).
const ALLOWED_ORIGINS = [
  "https://jrslaxx11.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];
const CACHE_SECONDS = 900; // 15 minutos
const QUOTE_CACHE_SECONDS = 60; // precios en vivo: 1 minuto
const MAX_QUOTES = 40; // el plan gratuito permite 50 peticiones internas por consulta
const UA = "Mozilla/5.0 (compatible; breakout-radar/1.0)";
// Nasdaq solo responde a peticiones con aspecto de navegador.
const NASDAQ_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
  "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/",
};

function cors(origin) {
  const ok = ALLOWED_ORIGINS.includes(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : ALLOWED_ORIGINS[0],
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

function json(body, status, origin, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(origin), ...extra },
  });
}

async function yahoo(url) {
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept": "application/json" } });
  if (!r.ok) throw Object.assign(new Error(`Yahoo respondió ${r.status}`), { status: r.status });
  return r.json();
}

async function chart(symbol) {
  const u = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
    "?range=2y&interval=1d&includePrePost=false&events=split";
  const j = await yahoo(u);
  const q = j?.chart?.result?.[0];
  if (!q || !q.timestamp) throw Object.assign(new Error("Ticker sin datos"), { status: 404 });
  const o = q.indicators.quote[0];
  const m = q.meta || {};
  const t = [], oo = [], hh = [], ll = [], cc = [], vv = [];
  const g = m.gmtoffset || 0;
  const day = (sec) => new Date((sec + g) * 1000).toISOString().slice(0, 10);
  const n = q.timestamp.length;
  for (let i = 0; i < n; i++) {
    let close = o.close[i];
    // Tras el cierre, Yahoo deja horas sin cierre la fila del día (EE. UU. y Europa): se toma de la cotización.
    if (close == null && i === n - 1 && m.regularMarketPrice && m.regularMarketTime && day(m.regularMarketTime) === day(q.timestamp[i])) {
      close = m.regularMarketPrice;
    }
    if (close == null || o.high[i] == null || o.low[i] == null) continue;
    t.push(day(q.timestamp[i]));
    oo.push(o.open[i] ?? close); hh.push(Math.max(o.high[i], close)); ll.push(Math.min(o.low[i], close)); cc.push(close);
    vv.push(o.volume[i] || 0);
  }
  return {
    symbol: m.symbol || symbol,
    meta: {
      currency: m.currency, exchange: m.fullExchangeName || m.exchangeName, name: m.longName || m.shortName || "",
      type: m.instrumentType, tz: m.exchangeTimezoneName, gmtoffset: g,
      sessionEnd: m.currentTradingPeriod?.regular?.end ?? null,
      // Última cotización: algunas bolsas tardan en añadir la sesión del día a la serie diaria.
      regularMarketTime: m.regularMarketTime ?? null, regularMarketPrice: m.regularMarketPrice ?? null,
      dayHigh: m.regularMarketDayHigh ?? null, dayLow: m.regularMarketDayLow ?? null,
      dayVolume: m.regularMarketVolume ?? null,
    },
    t, o: oo, h: hh, l: ll, c: cc, v: vv,
  };
}

// Último precio de un valor a partir de los metadatos del gráfico del día (no requiere sesión de Yahoo).
async function quoteOne(symbol) {
  const u = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1d&interval=1d`;
  const j = await yahoo(u);
  const r = j?.chart?.result?.[0];
  if (!r) return null;
  const m = r.meta || {};
  const q = r.indicators?.quote?.[0] || {};
  const reg = m.currentTradingPeriod?.regular || {};
  const now = Date.now() / 1000;
  const last = (a) => (Array.isArray(a) && a.length ? a[a.length - 1] : null);
  return {
    symbol: m.symbol || symbol, currency: m.currency, price: m.regularMarketPrice ?? null,
    prevClose: m.chartPreviousClose ?? m.previousClose ?? null, open: last(q.open),
    high: m.regularMarketDayHigh ?? null, low: m.regularMarketDayLow ?? null, volume: m.regularMarketVolume ?? null,
    time: m.regularMarketTime ?? null, gmtoffset: m.gmtoffset || 0,
    start: reg.start ?? null, end: reg.end ?? null, isOpen: !!(reg.start && reg.end && reg.start <= now && now < reg.end),
  };
}

async function quotes(list) {
  const out = {};
  await Promise.all(list.map(async (s) => {
    try { const q = await quoteOne(s); if (q) out[s] = q; } catch { /* ese valor queda sin precio */ }
  }));
  return { at: Math.floor(Date.now() / 1000), quotes: out };
}

// Pre-mercado de un valor de EE. UU. con las velas de 15 minutos de Yahoo (4:00-9:30 de Nueva York).
// Yahoo da el precio pero no el volumen del pre-mercado (ver nasdaqPre).
async function preOne(symbol) {
  const u = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1d&interval=15m&includePrePost=true`;
  const j = await yahoo(u);
  const r = j?.chart?.result?.[0];
  if (!r) return null;
  const m = r.meta || {}, q = r.indicators?.quote?.[0] || {}, ts = r.timestamp || [];
  const pre = m.currentTradingPeriod?.pre || {}, reg = m.currentTradingPeriod?.regular || {};
  if (!pre.start || !pre.end) return null;
  let price = null, high = null, low = null, open = null, time = null, bars = 0;
  for (let i = 0; i < ts.length; i++) {
    const c = q.close?.[i];
    if (ts[i] < pre.start || ts[i] >= pre.end || c == null) continue;
    const h = q.high?.[i] ?? c, l = q.low?.[i] ?? c;
    if (open === null) open = q.open?.[i] ?? c;
    high = high === null ? h : Math.max(high, h);
    low = low === null ? l : Math.min(low, l);
    price = c; time = ts[i]; bars++;
  }
  // Cierre de referencia: hasta que abre la sesión, el último precio regular de Yahoo es el cierre anterior
  // (y su "previousClose" todavía es el de dos sesiones atrás); una vez abierta, es "previousClose".
  const opened = m.regularMarketTime != null && reg.start != null && m.regularMarketTime >= reg.start;
  const prevClose = opened ? (m.chartPreviousClose ?? m.previousClose ?? null) : (m.regularMarketPrice ?? null);
  return {
    symbol: m.symbol || symbol, price, high, low, open, time, bars, prevClose,
    regPrice: opened ? (m.regularMarketPrice ?? null) : null,
    preStart: pre.start, preEnd: pre.end, regStart: reg.start ?? null, regEnd: reg.end ?? null,
  };
}

async function preQuotes(list) {
  const out = {};
  await Promise.all(list.map(async (s) => {
    try { const q = await preOne(s); if (q) out[s] = q; } catch { /* ese valor queda sin pre-mercado */ }
  }));
  return { at: Math.floor(Date.now() / 1000), quotes: out };
}

// Pre-mercado según Nasdaq (cubre también los valores de la NYSE): último precio consolidado, variación,
// máximo, mínimo, volumen y hora de la última operación. Es más completo que Yahoo en valores poco
// negociados, donde las velas de Yahoo se saltan operaciones.
const numOf = (x) => { const k = String(x ?? "").replace(/,/g, "").match(/-?\d+(\.\d+)?/); return k ? Number(k[0]) : null; };
async function nasdaqPre(symbol) {
  const s = symbol.replace("-", ".");   // BRK-B en Yahoo es BRK.B en Nasdaq
  const u = `https://api.nasdaq.com/api/quote/${encodeURIComponent(s)}/extended-trading?markettype=pre&assetclass=stocks`;
  const r = await fetch(u, { headers: NASDAQ_HEADERS, signal: AbortSignal.timeout(8000) });
  if (!r.ok) throw new Error(`Nasdaq respondió ${r.status}`);
  const j = await r.json();
  if (!j || !j.data) return null;
  const row = j.data.infoTable?.rows?.[0];
  const volume = row ? numOf(row.volume) : null;
  // Sin fila de resumen o sin volumen: Nasdaq no tiene pre-mercado de ese valor hoy.
  if (volume === null) return { volume: 0, last: null, change: null, high: null, low: null, time: null };
  const cons = String(row.consolidated ?? "").replace(/,/g, "").match(/(-?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)/);
  // Hora de la última operación (reloj de Nueva York), en segundos desde medianoche.
  const hm = String(j.data.tradeDetailTable?.rows?.[0]?.time ?? "").match(/^(\d{1,2}):(\d{2}):(\d{2})/);
  return {
    volume, last: cons ? Number(cons[1]) : numOf(row.consolidated), change: cons ? Number(cons[2]) : null,
    high: numOf(row.highPrice), low: numOf(row.lowPrice),
    time: hm ? Number(hm[1]) * 3600 + Number(hm[2]) * 60 + Number(hm[3]) : null,
  };
}

async function preVolumes(list) {
  const out = {};
  let failed = 0;
  await Promise.all(list.map(async (s) => {
    try { const q = await nasdaqPre(s); if (q) out[s] = q; } catch { failed++; }
  }));
  return { at: Math.floor(Date.now() / 1000), source: "Nasdaq", vol: out, failed };
}

async function search(q) {
  const u = `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=8&newsCount=0&listsCount=0`;
  const j = await yahoo(u);
  return (j.quotes || [])
    .filter((x) => x.symbol && (x.quoteType === "EQUITY" || x.quoteType === "ETF"))
    .map((x) => ({ symbol: x.symbol, name: x.longname || x.shortname || "", exchange: x.exchDisp || x.exchange, type: x.quoteType }));
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });
    if (request.method !== "GET") return json({ error: "Solo GET" }, 405, origin);

    const url = new URL(request.url);
    const cache = caches.default;
    const hit = await cache.match(request);
    if (hit) {
      const res = new Response(hit.body, hit);
      Object.entries(cors(origin)).forEach(([k, v]) => res.headers.set(k, v));
      return res;
    }
    try {
      let body, ttl = CACHE_SECONDS;
      if (url.pathname === "/chart") {
        const s = (url.searchParams.get("symbol") || "").trim().toUpperCase();
        if (!/^[A-Z0-9.^=\-]{1,20}$/.test(s)) return json({ error: "Ticker no válido" }, 400, origin);
        body = await chart(s);
      } else if (url.pathname === "/quote") {
        const list = [...new Set((url.searchParams.get("symbols") || "").toUpperCase().split(",").map((x) => x.trim()).filter(Boolean))];
        if (!list.length || list.length > MAX_QUOTES || !list.every((x) => /^[A-Z0-9.^=\-]{1,20}$/.test(x))) {
          return json({ error: `Lista no válida (hasta ${MAX_QUOTES} tickers separados por comas)` }, 400, origin);
        }
        body = await quotes(list);
        ttl = QUOTE_CACHE_SECONDS;
      } else if (url.pathname === "/pre" || url.pathname === "/prevol") {
        const list = [...new Set((url.searchParams.get("symbols") || "").toUpperCase().split(",").map((x) => x.trim()).filter(Boolean))];
        if (!list.length || list.length > MAX_QUOTES || !list.every((x) => /^[A-Z0-9.^=\-]{1,20}$/.test(x))) {
          return json({ error: `Lista no válida (hasta ${MAX_QUOTES} tickers separados por comas)` }, 400, origin);
        }
        body = url.pathname === "/pre" ? await preQuotes(list) : await preVolumes(list);
        ttl = QUOTE_CACHE_SECONDS;
      } else if (url.pathname === "/search") {
        const q = (url.searchParams.get("q") || "").trim();
        if (q.length < 1 || q.length > 40) return json({ error: "Búsqueda no válida" }, 400, origin);
        body = await search(q);
      } else {
        return json({ ok: true, uso: "/chart?symbol=AAPL · /search?q=apple · /quote?symbols=AAPL,MSFT · /pre?symbols=AAPL,MSFT · /prevol?symbols=AAPL,MSFT" }, 200, origin);
      }
      const res = json(body, 200, origin, { "Cache-Control": `public, max-age=${ttl}` });
      ctx.waitUntil(cache.put(request, res.clone()));
      return res;
    } catch (err) {
      return json({ error: err.message || "Error" }, err.status || 502, origin);
    }
  },
};
