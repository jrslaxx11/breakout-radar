"""Sectores calientes (radar/heat.py)."""
from types import SimpleNamespace

from radar import heat


def _row(sym, group, mom3, adr=0.06, scan=True):
    m = SimpleNamespace(mom1=mom3 / 3, mom3=mom3, mom6=mom3 * 1.5, adr_pct=adr)
    return {"sym": sym, "group": group, "m": m, "scan": ["3 m"] if scan else []}


def test_hot_groups_rank_by_heat():
    rows = [_row(f"S{i}", "Solar", 1.2) for i in range(5)] + [_row(f"N{i}", "Solar", 0.1, scan=False) for i in range(5)]
    rows += [_row(f"B{i}", "Biotechnology", 0.9, adr=0.03, scan=i < 3) for i in range(6)]
    rows += [_row("U1", "Uranium", 2.0), _row("U2", "Uranium", 1.5)]
    # Sector enorme con algunos valores en el escáner por azar: más valores que Biotecnología, pero frío.
    rows += [_row(f"X{i}", "Banks - Regional", 0.4, scan=i < 4) for i in range(60)]
    g = heat.hot_groups(rows, {"hot_min": 3, "hot_top": 8}, prev={"Solar": 2})
    assert [x["group"] for x in g] == ["Solar", "Uranium", "Biotechnology", "Banks - Regional"]
    solar = g[0]
    assert solar["scan_n"] == 5 and solar["n"] == 10 and solar["share"] == 0.5 and solar["fast_n"] == 5
    assert solar["heat"] == 2.5 and solar["hot"] and solar["prev_scan_n"] == 2 and solar["name"] == "Solar"
    assert not g[1]["hot"] and g[1]["top"] == ["U1", "U2"]  # solo 2 en el escáner
    assert g[2]["hot"] and g[2]["fast_n"] == 0 and g[2]["name"] == "Biotecnología"
    banks = g[3]
    assert banks["scan_n"] == 4 and not banks["hot"]          # 4 de 60 (7%): su cuota normal, no caliente


def test_scan_hits_and_group():
    m = SimpleNamespace(mom1=0.5, mom3=0.2, mom6=None)
    assert heat.scan_hits(m, {"mom1": 0.4, "mom3": 0.6, "mom6": 1.0}) == ["1 m"]
    assert heat.group_of({"gics_sub": "Semiconductors"}, {"industry": "Solar"}) == "Solar"
    assert heat.group_of({"gics_sub": "Semiconductors"}, {}) == "Semiconductors"
    assert heat.group_of({"gics_sub": "Application Software"}, {}) == "Software - Application"
    assert heat.group_of({}, None) is None
    assert heat.group_of({"gics_sub": "Semiconductors"}, {"industry": "Solar"}, "Banks—Regional") == "Banks - Regional"


def test_us_industries_screener_and_cache(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from radar import fundamentals as f
    monkeypatch.setattr(f, "INDUSTRY_CACHE", tmp_path / "industries.json")
    monkeypatch.setattr(f, "CACHE_DIR", tmp_path)
    calls = []

    def screen(ind, offset):
        calls.append((ind, offset))
        n = {"Biotechnology": 300, "Uranium": 4, "Software—Application": 1}[ind]  # biotecnología: dos páginas
        return [{"symbol": f"{ind[:3].upper()}{i}"} for i in range(offset, min(n, offset + 250))]
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    m = f.us_industries({"min_total": 10, "pause_s": 0}, screen=screen,
                        industries=["Biotechnology", "Uranium", "Software—Application"], now=now)
    assert len(m) == 305 and m["URA3"] == "Uranium" and m["BIO299"] == "Biotechnology"
    assert m["SOF0"] == "Software - Application"            # mismo nombre que en el perfil
    assert calls == [("Biotechnology", 0), ("Biotechnology", 250), ("Uranium", 0), ("Software—Application", 0)]
    # Caché semanal: no vuelve a consultar.
    m2 = f.us_industries({"min_total": 10}, screen=lambda i, o: 1 / 0, industries=["Uranium"], now=now + timedelta(days=3))
    assert m2 == m
    # Si el screener falla, se conserva la caché anterior.
    m3 = f.us_industries({"min_total": 10, "pause_s": 0}, screen=lambda i, o: 1 / 0, industries=["Uranium"] * 6,
                         now=now + timedelta(days=9))
    assert m3 == m


def test_profiles_retry_empty(tmp_path, monkeypatch):
    from datetime import date

    from radar import fundamentals as f
    monkeypatch.setattr(f, "PROFILE_CACHE", tmp_path / "profiles.json")
    monkeypatch.setattr(f, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(f.time, "sleep", lambda s: None)
    answers = {"A": {}, "B": {"longName": "B Corp", "industry": "Solar"}}
    c = f.profiles(["A", "B"], 10, today=date(2026, 11, 2), fetch=lambda s: answers[s])
    assert c["A"]["tries"] == 1 and c["B"]["industry"] == "Solar"
    # Al día siguiente no se reintenta; a los 8 días sí, y responde.
    answers["A"] = {"longName": "A Inc", "industry": "Uranium"}
    assert f.profiles(["A", "B"], 10, today=date(2026, 11, 3), fetch=lambda s: answers[s])["A"]["industry"] == ""
    assert f.profiles(["A", "B"], 10, today=date(2026, 11, 10), fetch=lambda s: answers[s])["A"]["industry"] == "Uranium"
    # 25 vacíos seguidos: Yahoo no responde y se para.
    seen = []
    f.profiles([f"Z{i}" for i in range(40)], 100, today=date(2026, 11, 10), fetch=lambda s: seen.append(s) or {})
    assert len(seen) == 25
