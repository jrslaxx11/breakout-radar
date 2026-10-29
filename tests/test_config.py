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
