"""Descarga de precios diarios (Yahoo Finance vía yfinance)."""
from __future__ import annotations

import logging
import time

import pandas as pd

log = logging.getLogger(__name__)

FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _split_download(df: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return out
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = set(df.columns.get_level_values(0))
        for t in tickers:
            if t not in lvl0:
                continue
            sub = df[t]
            sub = sub[[c for c in FIELDS if c in sub.columns]].dropna(subset=["Close", "High", "Low"])
            if not sub.empty:
                out[t] = sub
    else:  # un solo ticker
        sub = df[[c for c in FIELDS if c in df.columns]].dropna(subset=["Close", "High", "Low"])
        if not sub.empty and len(tickers) == 1:
            out[tickers[0]] = sub
    return out


def download(tickers: list[str], days: int, chunk: int = 80, pause: float = 2.0,
             retries: int = 3) -> dict[str, pd.DataFrame]:
    """OHLCV diario ajustado por splits (no por dividendos), como TradingView por defecto."""
    import yfinance as yf

    period = "2y" if days > 250 else "1y"   # yfinance solo acepta periodos estándar
    data: dict[str, pd.DataFrame] = {}
    tickers = list(dict.fromkeys(tickers))
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        for attempt in range(retries):
            try:
                df = yf.download(part, period=period, interval="1d", group_by="ticker",
                                 auto_adjust=False, actions=False, threads=True, progress=False)
                got = _split_download(df, part)
                data.update(got)
                missing = [t for t in part if t not in got]
                if missing and attempt < retries - 1 and len(missing) > len(part) // 2:
                    raise RuntimeError(f"{len(missing)} sin datos")
                break
            except Exception as exc:  # noqa: BLE001
                wait = pause * (attempt + 2) * 5
                log.warning("bloque %d falló (%s); reintento en %.0fs", i // chunk, exc, wait)
                time.sleep(wait)
        time.sleep(pause)
    # Segundo intento individual para los que faltan (suele ser bloqueo puntual).
    missing = [t for t in tickers if t not in data]
    if missing and len(missing) < 300:
        for t in missing:
            try:
                df = yf.download(t, period=period, interval="1d", auto_adjust=False,
                                 actions=False, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                got = _split_download(df, [t])
                data.update(got)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
    log.info("precios: %d de %d tickers", len(data), len(tickers))
    return data
