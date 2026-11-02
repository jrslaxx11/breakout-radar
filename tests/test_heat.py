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
