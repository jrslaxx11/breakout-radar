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


# ---------------------------------------------------------------------------------------------
# Calidad de la última barra
# ---------------------------------------------------------------------------------------------
def market_of(sym: str, mc: dict) -> str:
    """Clave de mercado (sufijo) de un ticker o índice; '' = EE. UU."""
    if sym.startswith("^"):
        return mc.get("indices", {}).get(sym, "")
    return sym.rsplit(".", 1)[1] if "." in sym else ""


def drop_partial_bars(data: dict, mc: dict, now_utc=None) -> list[str]:
    """Quita la barra de hoy si su mercado aún no ha cerrado (ejecuciones a deshora)."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    now_utc = now_utc or datetime.now(timezone.utc)
    dropped = []
    for sym, df in data.items():
        if sym.endswith("=X") or df is None or not len(df):
            continue
        key = market_of(sym, mc)
        tz, close = mc["by_suffix"].get(key, mc["default"])
        local = now_utc.astimezone(ZoneInfo(tz))
        hh, mm = (int(x) for x in close.split(":"))
        close_dt = local.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(minutes=20)
        last = pd.Timestamp(df.index[-1]).date()
        if last == local.date() and local < close_dt:
            data[sym] = df.iloc[:-1]
            dropped.append(sym)
    return dropped


def complete_recent(data: dict, mc: dict, chunk: int = 60, pause: float = 1.0) -> dict:
    """Yahoo a veces tarda horas en añadir la última sesión a las series largas.

    Para cada mercado se toma como sesión esperada la fecha más reciente de sus valores; los que
    se queden atrás se completan con una descarga corta (5 días). Devuelve los que siguen atrasados.
    """
    import yfinance as yf

    groups: dict[str, list[str]] = {}
    for sym, df in data.items():
        if sym.endswith("=X") or df is None or not len(df):
            continue
        groups.setdefault(market_of(sym, mc), []).append(sym)
    stale: dict[str, object] = {}
    for key, syms in groups.items():
        # Sesión esperada: la fecha más reciente que comparten al menos el 5% de los valores
        # del mercado (y un mínimo de 3), para que un dato erróneo aislado no marque a todos.
        counts: dict = {}
        for s in syms:
            d = pd.Timestamp(data[s].index[-1]).date()
            counts[d] = counts.get(d, 0) + 1
        need = max(3, int(0.05 * len(syms))) if len(syms) >= 3 else 1
        expected = next((d for d in sorted(counts, reverse=True) if counts[d] >= need), max(counts))
        for s in syms:
            if pd.Timestamp(data[s].index[-1]).date() < expected:
                stale[s] = expected
    todo = list(stale)
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        try:
            df = yf.download(part, period="5d", interval="1d", group_by="ticker", auto_adjust=False,
                             actions=False, threads=True, progress=False)
            recent = _split_download(df, part)
        except Exception as exc:  # noqa: BLE001
            log.warning("descarga corta falló: %s", exc)
            recent = {}
        for s, rdf in recent.items():
            base = data[s]
            last = pd.Timestamp(base.index[-1])
            exp = pd.Timestamp(stale[s])
            add = rdf[[last < pd.Timestamp(x) <= exp for x in rdf.index]]
            add = add[[c for c in base.columns if c in add.columns]]
            if len(add):
                data[s] = pd.concat([base, add])
        time.sleep(pause)
    still = {s: str(d) for s, d in stale.items() if pd.Timestamp(data[s].index[-1]).date() < d}
    log.info("última sesión: %d valores atrasados, %d completados, %d siguen atrasados",
             len(stale), len(stale) - len(still), len(still))
    return still
