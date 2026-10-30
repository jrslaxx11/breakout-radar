"""Calidad de la última barra: barras parciales y sesiones que Yahoo publica con retraso."""
import sys
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import radar.prices as P
from radar.config import Config

MC = Config.load().settings["market_close"]


def frame(dates):
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0},
                        index=pd.to_datetime(dates))


def test_drop_partial_bar_of_open_market():
    data = {"9101.T": frame(["2026-10-29", "2026-10-30"]), "IQV": frame(["2026-10-28", "2026-10-29"]),
            "EURUSD=X": frame(["2026-10-29", "2026-10-30"])}
    dropped = P.drop_partial_bars(data, MC, datetime(2026, 10, 30, 0, 45, tzinfo=timezone.utc))
    assert dropped == ["9101.T"]
    assert str(data["9101.T"].index[-1].date()) == "2026-10-29"
    assert str(data["EURUSD=X"].index[-1].date()) == "2026-10-30"  # divisas: 24 h


def test_keep_bar_after_close():
    data = {"9101.T": frame(["2026-10-29", "2026-10-30"])}
    assert P.drop_partial_bars(data, MC, datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)) == []


def test_complete_lagging_last_session(monkeypatch):
    def fake_download(part, **kw):
        cols = pd.MultiIndex.from_product([part, ["Open", "High", "Low", "Close", "Volume"]])
        idx = pd.to_datetime(["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"])
        return pd.DataFrame(np.ones((4, len(cols))), index=idx, columns=cols)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=fake_download))
    data = {f"U{i}": frame(["2026-10-28", "2026-10-29"]) for i in range(10)}
    data.update({f"S{i}": frame(["2026-10-27", "2026-10-28"]) for i in range(30)})
    still = P.complete_recent(data, MC, pause=0)
    assert still == {}
    # Se completa hasta la sesión esperada (29-oct), sin añadir la del 30-oct.
    assert str(data["S0"].index[-1].date()) == "2026-10-29"
