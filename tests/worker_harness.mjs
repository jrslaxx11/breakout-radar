// Prueba local del Worker con respuestas de Yahoo y Nasdaq como las observadas en el pre-mercado del 16-nov-2026.
const T0 = 1794819600;  // 09:00 UTC = 4:00 de Nueva York (inicio del pre-mercado)
let NOW = T0 + 3.3 * 3600;
const realNow = Date.now; Date.now = () => NOW * 1000;
const yahooPre = (opened) => ({ chart: { result: [{ meta: { symbol: "NVDA", regularMarketPrice: opened ? 158.2 : 162.85, regularMarketTime: opened ? T0 + 5.6 * 3600 : T0 - 12 * 3600,
  chartPreviousClose: opened ? 162.85 : 166.19, previousClose: opened ? 162.85 : 166.19,
  currentTradingPeriod: { pre: { start: T0, end: T0 + 19800 }, regular: { start: T0 + 19800, end: T0 + 43200 }, post: { start: T0 + 43200, end: T0 + 57600 } } },
  timestamp: [T0 - 300, T0, T0 + 300, T0 + 600, T0 + 11880, ...(opened ? [T0 + 19800, T0 + 20100] : [])],
  indicators: { quote: [{ open: [170, 160, 159.9, null, 157, 158, 158.1], high: [171, 163.15, 160.2, null, 157, 158.5, 158.3], low: [169, 159.8, 159.4, null, 156.53, 157.8, 158], close: [170, 159.98, 160, null, 157.06, 158.1, 158.2], volume: [0, 0, 0, null, 0, 5e6, 4e6] }] } }] } });
let opened = false, nasdaqOk = true;
globalThis.fetch = async (u) => {
  u = String(u);
  if (u.includes("query1.finance.yahoo.com")) return new Response(JSON.stringify(yahooPre(opened)), { status: 200 });
  if (u.includes("api.nasdaq.com")) {
    if (!nasdaqOk) return new Response("denied", { status: 403 });
    return new Response(JSON.stringify({ data: { infoTable: { rows: [{ consolidated: "$157.08 -5.77 (-3.54%)", volume: "10,170,575", highPrice: "$163.15 (04:00:00 AM)", lowPrice: "$156.53 (07:05:00 AM)" }] } } }), { status: 200 });
  }
  throw new Error("sin red: " + u);
};
globalThis.caches = { default: { match: async () => null, put: async () => {} } };
const W = (await import(process.argv[2])).default;
const call = async (path) => { const r = await W.fetch(new Request("https://w.test" + path, { headers: { Origin: "https://jrslaxx11.github.io" } }), {}, { waitUntil() {} }); return [r.status, await r.json()]; };
const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.error("FALLO", msg, a, b); process.exitCode = 1; } };
let [st, b] = await call("/pre?symbols=NVDA");
const q = b.quotes.NVDA;
eq(st, 200, "status"); eq([q.price, q.high, q.low, q.open, q.bars, q.prevClose, q.regPrice], [157.06, 163.15, 156.53, 160, 3, 162.85, null], "pre en vivo");
eq(q.time, T0 + 11880, "hora del último precio"); eq([q.preStart, q.preEnd], [T0, T0 + 19800], "horario");
opened = true; NOW = T0 + 5.7 * 3600;
[st, b] = await call("/pre?symbols=NVDA");
eq([b.quotes.NVDA.price, b.quotes.NVDA.bars, b.quotes.NVDA.prevClose, b.quotes.NVDA.regPrice], [157.06, 3, 162.85, 158.2], "tras la apertura: mismo pre-mercado y mismo cierre de referencia");
[st, b] = await call("/prevol?symbols=NVDA,BRK-B");
eq([b.vol.NVDA.volume, b.vol.NVDA.high, b.vol.NVDA.low, b.vol.NVDA.last, b.failed], [10170575, 163.15, 156.53, 157.08, 0], "volumen Nasdaq");
nasdaqOk = false;
[st, b] = await call("/prevol?symbols=NVDA");
eq([st, Object.keys(b.vol).length, b.failed], [200, 0, 1], "Nasdaq caído: sin volumen, sin error");
[st, b] = await call("/pre?symbols=" + Array.from({ length: 41 }, (_, i) => "A" + i).join(","));
eq(st, 400, "más de 40");
[st, b] = await call("/pre?symbols=NV<DA");
eq(st, 400, "ticker no válido");
console.log(process.exitCode ? "con fallos" : "worker ok");
