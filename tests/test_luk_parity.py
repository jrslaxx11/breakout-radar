"""Paridad del sistema de Luk entre Python (radar/luk.py) y el navegador (docs/luk-engine.js).

El navegador recalcula con el kit de docs/data/live.json (velas hasta ayer y colas de EMA) más la vela de hoy;
debe dar lo mismo que Python con la serie completa."""
import json
import math
import shutil
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from radar import calendar_us, luk
from radar.luk_run import bar_kit, health_kit

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js no disponible")


def _df(c, spread=0.025, vol=None, opens=None, seed=0):
    rng = np.random.default_rng(seed)
    c = np.asarray(c, float)
    n = len(c)
    o = c * (1 + rng.normal(0, 0.004, n)) if opens is None else np.asarray(opens, float)
    v = np.round(rng.uniform(0.6, 1.4, n) * 2e6) if vol is None else np.asarray(vol, float)
    h = np.maximum(c, o) * (1 + rng.uniform(0.3, 1.0, n) * spread)
    lo = np.minimum(c, o) * (1 - rng.uniform(0.3, 1.0, n) * spread)
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}, index=pd.bdate_range("2025-11-03", periods=n))


def _trend(pull, leg=0.025, n0=120):
    c = list(50 * np.cumprod(np.full(n0, 1.006)))
    for _ in range(15):
        c.append(c[-1] * (1 + leg))
    for r in pull:
        c.append(c[-1] * (1 + r))
    return c


def _cases():
    out = {
        "L1": _df(_trend([-0.02, -0.025, -0.02, -0.015])),
        "L1b": _df(_trend([-0.012] * 7, leg=0.012), seed=4),
        "L3": _df(_trend([]) + [_trend([])[-1] * x for x in (0.99, 1.0, 0.995, 1.002, 0.998, 1.0, 0.997, 1.001, 0.999, 1.0, 1.003)], spread=0.008, seed=2),
        "down": _df(list(100 * np.cumprod(np.full(180, 0.995))), seed=3),
        "rand": _df(list(30 * np.exp(np.cumsum(np.random.default_rng(9).normal(0.002, 0.03, 200)))), seed=4),
    }
    c = _trend([-0.01, -0.02, -0.02])                     # EP hace 10 sesiones: ancla del AVWAP
    o = np.array(c) * 1.0
    v = np.round(np.full(len(c), 2e6))
    o[-10], v[-10] = c[-11] * 1.12, 9e6
    out["EP"] = _df(c, vol=v, opens=o, seed=5)
    return out


def _bar(df):
    r = df.iloc[-1]
    return {"t": df.index[-1].date().isoformat(), "o": float(r.Open), "h": float(r.High), "l": float(r.Low),
            "c": float(r.Close), "v": float(r.Volume), "vp": float(r.Volume)}


def test_luk_engine_matches_python(tmp_path):
    q = luk.cfg_of(None)
    cases, py = [], []
    for name, df in _cases().items():
        P0 = luk.prepare(df.iloc[:-1], q)
        cases.append({"kit": bar_kit(P0, P0["n"] - 1, rnd=False), "bar": _bar(df), "earn": 3})
        P = luk.prepare(df, q)
        py.append((name, luk.analyze(P, P["n"] - 1, q, True), P))
    health = []
    for name, df in _cases().items():
        P0 = luk.prepare(df.iloc[:-1], q)
        kh = health_kit(P0, P0["n"] - 1, q)
        kh = {**kh, **{f"e{k}": [float(x) if np.isfinite(x) else None for x in P0[f"e{k}"][P0["n"] - 5:P0["n"]]] for k in (9, 21, 50, 150)},
              "c": float(P0["c"][-1]), "adr": float(P0["adr"][-1])}
        health.append({"kit": kh, "bar": _bar(df)})
    sessions = [["2026-11-24", "2026-11-30"], ["2026-11-05", "2026-11-05"], ["2026-11-05", "2026-11-04"], ["2026-12-23", "2027-01-04"]]
    job = {"q": q, "cases": cases, "health": health, "sessions": sessions,
           "holidays": sorted(d.isoformat() for y in (2026, 2027) for d in calendar_us.holidays(y))}
    f = tmp_path / "job.json"
    f.write_text(json.dumps(job))
    res = json.loads(subprocess.run(["node", str(ROOT / "tests" / "luk_parity_harness.js"), str(f)],
                                    capture_output=True, text=True, check=True).stdout)
    seen = set()
    for (name, a, P), js, sc, lv in zip(py, res["analyze"], res["score"], res["levels"]):
        assert (a is None) == (js is None), name
        if a is None:
            continue
        seen.add(a["setup"])
        for k in ("setup", "leader", "days", "anchor", "anchor_date", "touch", "zone", "support", "recovery", "inside",
                  "nr7", "e9up", "e21up", "ep_today", "high_date"):
            assert a[k] == js[k], (name, k, a[k], js[k])
        assert bool(a["why"]) == bool(js["why"]), (name, a["why"], js["why"])
        for k in ("depth_adr", "retrace", "dist_adr", "avwap", "ema9", "ema21", "ema50", "leg", "adr", "pull_lo",
                  "vol_ratio", "dist52", "wide_day", "support_value"):
            if a.get(k) is None:
                assert js.get(k) is None, (name, k)
            else:
                assert math.isclose(a[k], js[k], rel_tol=1e-9, abs_tol=1e-12), (name, k, a[k], js[k])
        if a["setup"] in luk.SETUPS:
            ps = luk.score(a, 0.8, 2, 3, True, q)
            assert math.isclose(ps["score"], sc["score"], abs_tol=0.051) and ps["flags"] == sc["flags"], name
        if a["setup"]:
            pl = luk.levels(a, q)
            assert math.isclose(pl["entry"], lv["entry"]) and pl["trigger"] == lv["trigger"] and pl["level"] == lv["level"], name
    assert {"L1", "L1b", "L3"} <= seen
    for (name, _, P), hj in zip(py, res["health"]):
        assert luk.health(P, P["n"] - 1, q) == hj["st"], name
        cx = luk.context(P, P["n"] - 1, q)
        assert cx["order"] == hj["ctx"]["order"] and cx["status"] == hj["ctx"]["status"], name
        assert math.isclose(cx["vs21"], hj["ctx"]["vs21"], rel_tol=1e-9), name
    assert res["sessions"] == [calendar_us.sessions_until(date.fromisoformat(a), date.fromisoformat(b)) for a, b in sessions]
