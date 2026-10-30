/**
 * Radar de rupturas · intermediario para buscar cualquier ticker.
 *
 * El navegador no puede pedir datos a Yahoo Finance directamente (CORS). Este Worker de
 * Cloudflare (plan gratuito: 100.000 peticiones al día) hace la petición y devuelve solo lo
 * necesario, con permiso para que tu web lo lea. No guarda nada ni necesita claves.
 *
 *   GET /chart?symbol=AAPL   → velas diarias de 2 años + metadatos
 *   GET /search?q=apple      → sugerencias de tickers
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
const UA = "Mozilla/5.0 (compatible; breakout-radar/1.0)";

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
      let body;
      if (url.pathname === "/chart") {
        const s = (url.searchParams.get("symbol") || "").trim().toUpperCase();
        if (!/^[A-Z0-9.^=\-]{1,20}$/.test(s)) return json({ error: "Ticker no válido" }, 400, origin);
        body = await chart(s);
      } else if (url.pathname === "/search") {
        const q = (url.searchParams.get("q") || "").trim();
        if (q.length < 1 || q.length > 40) return json({ error: "Búsqueda no válida" }, 400, origin);
        body = await search(q);
      } else {
        return json({ ok: true, uso: "/chart?symbol=AAPL · /search?q=apple" }, 200, origin);
      }
      const res = json(body, 200, origin, { "Cache-Control": `public, max-age=${CACHE_SECONDS}` });
      ctx.waitUntil(cache.put(request, res.clone()));
      return res;
    } catch (err) {
      return json({ error: err.message || "Error" }, err.status || 502, origin);
    }
  },
};
