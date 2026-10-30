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


def quote(t_utc, px, state="POSTPOST", tz="America/New_York", hi=None, lo=None, op=None, vol=1000):
    return {"regularMarketTime": int(t_utc.timestamp()), "regularMarketPrice": px, "marketState": state,
            "regularMarketDayHigh": hi or px * 1.01, "regularMarketDayLow": lo or px * 0.99,
            "regularMarketOpen": op or px, "regularMarketVolume": vol, "exchangeTimezoneName": tz}


def test_patch_last_session_from_quotes():
    close_us = datetime(2026, 10, 29, 20, 0, 3, tzinfo=timezone.utc)
    data = {"IQV": frame(["2026-10-27", "2026-10-28"]), "SAP.DE": frame(["2026-10-27", "2026-10-28"]),
            "7203.T": frame(["2026-10-28", "2026-10-29"]), "AAPL": frame(["2026-10-28", "2026-10-29"]),
            "^STOXX": frame(["2026-10-27", "2026-10-28"])}
    quotes = {
        "IQV": quote(close_us, 275.06, op=276.86, hi=279.36, lo=272.895, vol=1423953),
        "SAP.DE": quote(datetime(2026, 10, 29, 16, 38, tzinfo=timezone.utc), 208.9, "PREPRE", "Europe/Berlin"),
        "7203.T": quote(datetime(2026, 10, 30, 0, 37, tzinfo=timezone.utc), 3096.0, "REGULAR", "Asia/Tokyo"),
        "AAPL": quote(close_us, 348.91),  # ya tiene la sesión: no se duplica
        "^STOXX": quote(datetime(2026, 10, 29, 17, 0, tzinfo=timezone.utc), 649.11, "PREPRE", "Europe/Zurich", hi=0.0, lo=0.0),
    }
    now = datetime(2026, 10, 30, 0, 52, tzinfo=timezone.utc)
    patched = P.patch_from_quotes(data, quotes, MC, now)
    assert sorted(patched) == ["IQV", "SAP.DE", "^STOXX"]
    iqv = data["IQV"].iloc[-1]
    assert str(data["IQV"].index[-1].date()) == "2026-10-29"
    assert (iqv["Open"], iqv["High"], iqv["Low"], iqv["Close"], iqv["Volume"]) == (276.86, 279.36, 272.895, 275.06, 1423953)
    assert len(data["AAPL"]) == 2 and str(data["7203.T"].index[-1].date()) == "2026-10-29"
    assert data["^STOXX"].iloc[-1]["Close"] == 649.11


def test_no_patch_right_after_close():
    data = {"IQV": frame(["2026-10-28"])}
    t = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)
    assert P.patch_from_quotes(data, {"IQV": quote(t, 275.0, "POST")}, MC, datetime(2026, 10, 29, 20, 5, tzinfo=timezone.utc)) == []


def test_expected_session_by_market():
    now = datetime(2026, 10, 30, 0, 52, tzinfo=timezone.utc)  # viernes 09:52 en Tokio
    assert str(P.expected_session("IQV", MC, now)) == "2026-10-29"
    assert str(P.expected_session("SAP.DE", MC, now)) == "2026-10-29"
    assert str(P.expected_session("7203.T", MC, now)) == "2026-10-29"   # Tokio sigue abierto
    sat = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    assert str(P.expected_session("IQV", MC, sat)) == "2026-10-30"


def test_quote_from_chart_metadata():
    class FakeYd:
        def get_raw_json(self, url, params=None):
            return {"chart": {"result": [{
                "meta": {"regularMarketTime": 1793304003, "regularMarketPrice": 275.06, "regularMarketDayHigh": 279.36,
                         "regularMarketDayLow": 272.895, "regularMarketVolume": 1423953,
                         "exchangeTimezoneName": "America/New_York",
                         "currentTradingPeriod": {"regular": {"start": 1793280600, "end": 1793304000}}},
                "timestamp": [1793194200, 1793280600],
                "indicators": {"quote": [{"open": [270.1, 276.86], "close": [279.04, None]}]}}]}}

    q = P._quote_v8(FakeYd(), "IQV", 1793321520)
    assert q["marketState"] == "CLOSED" and q["regularMarketOpen"] == 276.86 and q["regularMarketPrice"] == 275.06
    data = {"IQV": frame(["2026-10-27", "2026-10-28"])}
    assert P.patch_from_quotes(data, {"IQV": q}, MC, datetime(2026, 10, 30, 0, 52, tzinfo=timezone.utc)) == ["IQV"]
    assert str(data["IQV"].index[-1].date()) == "2026-10-29" and data["IQV"].iloc[-1]["Open"] == 276.86
