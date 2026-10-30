// Ejecuta docs/engine.js sobre las series de un JSON y escribe los resultados (prueba de paridad).
const fs = require("fs");
const E = require("../docs/engine.js");
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
for (const k of job.series) out[k.symbol] = E.evaluateTicker(k, job.ctx);
process.stdout.write(JSON.stringify(out));
