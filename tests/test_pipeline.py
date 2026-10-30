"""Prueba de extremo a extremo con un universo sintético (sin red)."""
from datetime import date

import numpy as np
import pandas as pd

from radar.config import Config
from radar.pipeline import run

SUBS = ["Life Sciences Tools & Services", "Application Software", "Regional Banks", "Semiconductors"]


def fake_prices(n=300, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-08-01", periods=n)
    out = {}

    def make(drift, vol=0.015, level=100.0, volume=2e6):
        r = rng.normal(drift, vol, n)
        c = level * np.exp(np.cumsum(r))
        h = c * (1 + rng.uniform(0.002, 0.02, n))
        l = c * (1 - rng.uniform(0.002, 0.02, n))
        o = c * (1 + rng.normal(0, 0.003, n))
        v = volume * rng.uniform(0.6, 1.4, n)
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)

    universe = {}
    for i, sub in enumerate(SUBS):
        for j in range(12):
            sym = f"T{i}{j:02d}"
            out[sym] = make(drift=0.0015 * (3 - i) / 3 + rng.normal(0, 0.0005))
            universe[sym] = {"source": ["SPX", "MID", "SML"][j % 3], "name": sym, "gics_sector": "",
                             "gics_sub": sub, "hint": "", "unbiased": True}
    cfg = Config.load()
    S = cfg.settings
    extra = [i["sym"] for i in S["regime"]["indices"]] + S["regime"]["volatility"]
    extra += sorted({S["benchmarks"]["default"], *S["benchmarks"]["by_suffix"].values()})
    extra += sorted({e for t in cfg.theme_defs.values() for e in (t.get("etfs") or [])})
    extra += cfg.themes.get("reference_etfs", [])
    for s in set(extra):
        out[s] = make(drift=0.0004, level=50 if not s.startswith("^") else 4000)
    for spec in S["fx"].values():
        out[spec["pair"]] = make(0, 0.002, level=1.1)
    return universe, out


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    import radar.history as h
    monkeypatch.setattr(h, "HISTORY_DIR", tmp_path)
    universe, prices = fake_prices()
    details = lambda syms: {s: {"name": s, "mcap": 5e9, "currency": "USD", "exchange": "NYSE",  # noqa: E731
                                "country": "United States", "tz": "America/New_York",
                                "last_earnings": None, "next_earnings": "2026-12-01",
                                "next_earnings_est": True} for s in syms}
    out = run(universe=universe, prices=prices, details_fn=details, profiles_fn=lambda s, l: {},
              today=date(2026, 10, 29), write=False, force=True)
    assert out["regime"]["label"] in ("FAVORABLE", "MIXTO", "DESFAVORABLE")
    keys = {t["key"] for t in out["themes"]}
    assert {"LST", "SW", "BANK", "SEMI"} <= keys
    assert out["selected_themes"], "debe seleccionar temáticas"
    for c in out["candidates"]:
        assert 0 <= c["score"] <= 100
        assert c["state"] in ("CONFIRMADA", "TEMPRANA", "PRE-BREAKOUT", "RETEST", "EXTENDIDA", "EN BASE", "DESCARTADA")
    # Puntuación de temáticas: sin catalizador, componentes dentro de sus pesos y suma = total.
    w = out["theme_weights"]
    assert sum(w.values()) == 100 and "catalyst" not in w
    for t in out["themes"]:
        sc = t["score"]
        assert all(0 <= sc[k] <= w[k] + 1e-9 for k in w)
        assert abs(sum(sc[k] for k in w) - sc["total"]) < 0.01
    best = max(out["themes"], key=lambda t: t["rsc"])
    assert best["rs_rank"] == 1 and best["score"]["rs"] == w["rs"]
    # Líderes de cada temática: hasta 10, ordenadas por fuerza relativa.
    for t in out["themes"]:
        rs = [x["rs_pct"] for x in t["top"]]
        assert 0 < len(rs) <= 10 and rs == sorted(rs, reverse=True)
        assert all(x["state"] and x["score"] is not None for x in t["top"])
    pres = out["lists"]["presented"]
    assert len(pres) == len(set(pres))
    assert all(out["candidates"][0]["score"] >= c["score"] for c in out["candidates"])
    # La amplitud del S&P se calcula con los grupos SPX/MID/SML del universo.
    assert out["regime"]["breadth"]["SPX"]["now"]["n"] > 0
