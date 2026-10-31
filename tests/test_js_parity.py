"""Paridad entre el motor de Python y el del navegador (docs/engine.js) con datos sintéticos."""
import json
import math
import shutil
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from radar.pipeline import run
from tests.test_pipeline import fake_prices

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js no disponible")


def shaped(kind: str, n: int = 300, seed: int = 3) -> pd.DataFrame:
    """Series con forma de ruptura, pre-ruptura, extendida y ruptura fallida."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-08-01", periods=n)
    c = np.empty(n)
    c[:220] = 50 * np.exp(np.cumsum(rng.normal(0.0008, 0.01, 220)))
    c[220:260] = c[219] * np.exp(np.cumsum(np.full(40, 0.012)))           # subida previa ≈ 60%
    top = c[259]
    c[260:n] = top * (0.93 + 0.04 * rng.random(n - 260))                    # base de 40 sesiones
    v = 3e6 * rng.uniform(0.7, 1.3, n)
    if kind == "BRK":
        c[-1] = top * 1.04
        v[-1] = 1.2e7
    elif kind == "PRE":
        c[-5:] = top * np.array([0.965, 0.97, 0.975, 0.97, 0.98])
    elif kind == "EXT":
        c[-6:] = top * np.array([1.03, 1.07, 1.10, 1.14, 1.18, 1.22])
    elif kind == "FAIL":
        c[-4:] = top * np.array([1.03, 1.0, 0.96, 0.94])
    h = c * (1 + rng.uniform(0.004, 0.03, n))
    l = c * (1 - rng.uniform(0.004, 0.03, n))
    h[260:-6] = np.minimum(h[260:-6], top * 0.999)
    o = c * (1 + rng.normal(0, 0.004, n))
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


def series(sym: str, df: pd.DataFrame) -> dict:
    return {"symbol": sym, "meta": {"currency": "USD"}, "t": [d.strftime("%Y-%m-%d") for d in df.index],
            **{k: [float(x) for x in df[col]] for k, col in
               (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"), ("v", "Volume"))}}


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


def test_engine_js_matches_python(tmp_path, monkeypatch):
    import radar.history as h
    monkeypatch.setattr(h, "HISTORY_DIR", tmp_path)
    universe, prices = fake_prices()
    for i, kind in enumerate(("BRK", "PRE", "EXT", "FAIL")):
        prices[kind] = shaped(kind, seed=10 + i)
        universe[kind] = {"source": "SPX", "name": kind, "gics_sector": "", "unbiased": True,
                          "gics_sub": "Application Software", "hint": ""}
    # Triángulos: ruptura de la resistencia descendente (por debajo del máximo) y pre-ruptura.
    from radar.metrics import compute as mcompute
    from tests.test_breakouts import W as BW, triangle
    for kind, mult, vol in (("TRI", 1.03, 2.5e6), ("TRIP", 0.975, 1e6)):
        df = triangle()
        df.index = prices["BRK"].index[-len(df):]
        lvl = mcompute(kind, df.iloc[:-1], BW).P
        c = lvl * mult
        # TRIP: mínimo de hoy por encima del suelo de la base (si lo perforase, la línea dejaría de valer).
        df.iloc[-1] = [c * 0.99, c * 1.005, c * 0.98, c, vol] if kind == "TRI" else [c, c * 1.004, c * 0.995, c, vol]
        prices[kind] = df
        universe[kind] = {"source": "SPX", "name": kind, "gics_sector": "", "unbiased": True,
                          "gics_sub": "Application Software", "hint": ""}
    # High tight flag: mástil del 150% en 35 sesiones y bandera estrecha.
    from tests.test_stars import _lows_on_sma10, high_tide_flag
    df = _lows_on_sma10(high_tide_flag(n=255))  # bandera de 20 sesiones
    df.index = prices["BRK"].index[-len(df):]
    prices["HTF"] = df
    universe["HTF"] = {"source": "SPX", "name": "HTF", "gics_sector": "", "unbiased": True,
                       "gics_sub": "Application Software", "hint": ""}
    out = run(universe=universe, prices=prices, details_fn=lambda s: {}, profiles_fn=lambda s, l: {},
              today=date(2026, 10, 29), write=False, force=True)
    ctx = json.loads(json.dumps(out["engine"]))
    view = {c["sym"]: c for c in out["search_view"]}
    syms = sorted(view)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"ctx": ctx, "series": [series(s, prices[s]) for s in syms]}))
    res = json.loads(subprocess.run(["node", str(ROOT / "tests" / "parity_harness.js"), str(job)],
                                    check=True, capture_output=True, text=True).stdout)

    states = set()
    for s in syms:
        py, js = view[s], res[s]
        states.add(py["state"])
        assert js["state"] == py["state"] and js["why"] == py["why"], s
        assert (js["level_kind"], js["line"][0][0], js["line"][1][0]) == (py["level_kind"], py["line"][0][0], py["line"][1][0]), s
        assert close(js["line"][1][1], py["line"][1][1]) and js.get("touch_date") == py.get("touch_date"), s
        for k in ("close", "pivot", "inv", "atr", "rvol", "vdry", "adr_pct", "rs_pct", "mdv_usd", "s10", "s20",
                  "peak", "retrace", "tight_ratio", "prior_move", "base_len", "depth"):
            assert close(js[k], py[k]), (s, k, js[k], py[k])
        for k in ("rs", "base", "breakout", "trend", "liquidity"):
            assert close(js["components"][k], py["components"][k]), (s, k)
        assert (js["confirm"], js["invalidate"]) == (py["confirm"], py["invalidate"]), s
        if py["components"]["catalyst"] is None:  # fuera de las candidatas: mismo riesgo y total
            assert (js["risk"], js["risk_points"]) == (py["risk"], py["risk_points"]), s
            assert close(js["score"], py["score"], 1e-6), s
        qj, qp = js["qm"], py["qm"]
        assert qj["verdict"] == qp["verdict"] and qj["entry_note"] == qp["entry_note"], s
        assert [(c["key"], c["ok"], c["value"]) for c in qj["checks"]] == \
               [(c["key"], c["ok"], c["value"]) for c in qp["checks"]], s
        assert close(qj["trigger"], qp["trigger"]) and close(qj["stop_max"], qp["stop_max"]), s
        # Estrellas: mismos puntos, criterios y textos (el JS no conoce la temática: sin bonificación).
        sj, sp = js["stars"], py["stars"]
        assert sj["points"] == sp["points"] and sj["chart_stars"] == sp["chart_stars"], s
        assert [(i["key"], i["pts"], i["value"]) for i in sj["items"]] == [(i["key"], i["pts"], i["value"]) for i in sp["items"]], s
        assert sj["penalties"] == sp["penalties"] and sj["pillars"] == sp["pillars"], s
        hj, hp = js["htf"], py["htf"]
        assert (hj is None) == (hp is None), s
        if hp:
            assert (hj["kind"], hj["text"], hj["pole_len"], hj["flag_len"], hj["pole_date"], hj["peak_date"], hj["flag_end"]) == \
                   (hp["kind"], hp["text"], hp["pole_len"], hp["flag_len"], hp["pole_date"], hp["peak_date"], hp["flag_end"]), s
            assert all(close(hj[k], hp[k]) for k in ("pole", "depth", "peak", "flag_low", "pole_lo")), s
    # Las series con forma garantizan que se prueban varios estados, no solo los aleatorios.
    assert len(states) >= 4, states
    assert view["TRI"]["state"] == "CONFIRMADA" and view["TRI"]["pivot"] < view["TRI"]["peak"] * 0.97
    assert view["TRIP"]["state"] == "PRE-BREAKOUT"
    assert view["HTF"]["htf"] and view["HTF"]["htf"]["kind"] == "clásica", view["HTF"]["htf"]
    assert any(x["sym"] == "HTF" for x in out["lists"]["htf_setups"])
    assert {c["level_kind"] for c in view.values()} >= {"línea", "máximo"}


def test_prepare_series_js():
    """Completa la sesión que Yahoo aún no ha añadido a la serie y descarta la barra de una sesión abierta."""
    script = r"""
    const E = require(process.argv[1]);
    const base = {symbol: "X", t: ["2026-10-28", "2026-10-29"], o: [1, 1], h: [2, 2], l: [1, 1], c: [1.5, 1.5], v: [10, 10]};
    const end = Date.UTC(2026, 9, 30, 6, 0) / 1000;  // cierre 15:00 en Tokio (gmtoffset +9 h)
    const meta = {gmtoffset: 32400, sessionEnd: end, regularMarketTime: end - 600, regularMarketPrice: 1.7,
                  dayHigh: 1.8, dayLow: 1.4, dayVolume: 7};
    const open = E.prepareSeries({...base, meta}, end - 3600);
    const done = E.prepareSeries({...base, meta}, end + 3600);
    console.log(JSON.stringify([open.partial, open.series.t.at(-1), done.partial, done.series.t.at(-1), done.series.c.at(-1)]));
    """
    r = subprocess.run(["node", "-e", script, str(ROOT / "docs" / "engine.js")], check=True, capture_output=True, text=True)
    assert json.loads(r.stdout) == [True, "2026-10-29", False, "2026-10-30", 1.7]
