// Ejecuta docs/luk-engine.js sobre los casos de un JSON (prueba de paridad con radar/luk.py).
const fs = require("fs");
const L = require("../docs/luk-engine.js");
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = { analyze: [], health: [], score: [], levels: [] };
for (const x of job.cases) {
  const a = L.analyze(x.kit, x.bar, job.q, true);
  out.analyze.push(a);
  out.score.push(a && L.SETUPS.includes(a.setup) ? L.score(a, 0.8, 2, x.earn, true, job.q) : null);
  out.levels.push(a && a.setup ? L.levels(a, job.q) : null);
}
for (const x of job.health) out.health.push({ st: L.health(x.kit, x.bar, job.q), ctx: L.context(x.kit, x.bar, job.q) });
out.sessions = job.sessions.map(([a, b]) => L.sessionsUntil(a, b, job.holidays));
process.stdout.write(JSON.stringify(out));
