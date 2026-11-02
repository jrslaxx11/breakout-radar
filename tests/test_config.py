"""La configuración se lee como se espera (YAML convierte `no`, `on`, `yes` en booleanos)."""
from radar.config import Config


def test_region_keys_are_strings():
    cfg = Config.load()
    d = cfg.settings["discovery"]
    assert all(isinstance(k, str) for k in d["regions"]), "pon entre comillas las claves de región"
    assert all(isinstance(k, str) for k in d["exchanges"])
    assert set(d["regions"]) == set(d["exchanges"])


def test_suffix_maps_are_strings():
    cfg = Config.load()
    assert all(isinstance(k, str) for k in cfg.settings["currency_by_suffix"])
    assert all(isinstance(k, str) for k in cfg.settings["benchmarks"]["by_suffix"])


def test_every_theme_has_a_name():
    cfg = Config.load()
    for key, t in cfg.theme_defs.items():
        assert t.get("name"), key


def test_us_universe_cache_and_filter(tmp_path, monkeypatch):
    import json
    import pandas as pd
    import radar.universe as U
    from radar.config import Config
    monkeypatch.setattr(U, "CACHE_DIR", tmp_path)
    listed = [{"symbol": f"S{i}", "name": f"S{i}", "exchange": "Nasdaq"} for i in range(3500)]
    idx = pd.bdate_range("2026-10-01", periods=22)

    def fake_download(syms, days, chunk, pause, period=None):
        assert period == "1mo"
        out = {}
        for k, s in enumerate(syms):
            px = 20.0 if k % 2 == 0 else 2.0                  # la mitad, por debajo del precio mínimo
            out[s] = pd.DataFrame({"Close": [px] * 22, "Volume": [1e6] * 22}, index=idx)
        return out
    cfg = Config.load()
    rows = U.us_liquid(cfg, download_fn=fake_download, listed_fn=lambda: listed)
    assert len(rows) == 1750 and all(r["mdv"] == 20_000_000 for r in rows)
    cached = json.loads((tmp_path / "us_liquid.json").read_text())
    assert cached["listed"] == 3500
    # Con la caché reciente no vuelve a descargar.
    assert U.us_liquid(cfg, download_fn=lambda *a, **k: 1 / 0, listed_fn=lambda: 1 / 0) == rows
