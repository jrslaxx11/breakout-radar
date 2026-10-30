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


QUOTE_FIELDS = ("regularMarketPrice,regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,"
                "regularMarketVolume,regularMarketTime,marketState,exchangeTimezoneName")


def expected_session(sym: str, mc: dict, now_utc):
    """Última sesión que ya debería estar cerrada en el mercado del valor (sin festivos)."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    tz, close = mc["by_suffix"].get(market_of(sym, mc), mc["default"])
    local = now_utc.astimezone(ZoneInfo(tz))
    hh, mm = (int(x) for x in close.split(":"))
    d = local.date()
    if local < local.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(minutes=20):
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _quotes_v7(yd, symbols: list[str], chunk: int, pause: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), chunk):
        j = yd.get_raw_json("https://query1.finance.yahoo.com/v7/finance/quote",
                            params={"symbols": ",".join(symbols[i:i + chunk]), "fields": QUOTE_FIELDS})
        for q in (j.get("quoteResponse") or {}).get("result") or []:
            if q.get("symbol"):
                out[q["symbol"]] = q
        time.sleep(pause)
    return out


def _quote_v8(yd, sym: str, now_ts: float) -> dict | None:
    """Mismos campos que la cotización, sacados de los metadatos del gráfico (no requiere sesión)."""
    j = yd.get_raw_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}",
                        params={"range": "5d", "interval": "1d"})
    r = ((j.get("chart") or {}).get("result") or [None])[0]
    if not r:
        return None
    m = r.get("meta") or {}
    reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    q = {k: m.get(k) for k in ("regularMarketTime", "regularMarketPrice", "regularMarketDayHigh",
                               "regularMarketDayLow", "regularMarketVolume", "exchangeTimezoneName")}
    q["marketState"] = "REGULAR" if reg.get("start", 0) <= now_ts < reg.get("end", 0) else "CLOSED"
    ts = r.get("timestamp") or []
    opens = (((r.get("indicators") or {}).get("quote") or [{}])[0]).get("open") or []
    if ts and opens and q["regularMarketTime"] and abs(q["regularMarketTime"] - ts[-1]) < 86400:
        q["regularMarketOpen"] = opens[-1]  # apertura de la fila del día (la que llega sin cierre)
    return q


def fetch_quotes(symbols: list[str], chunk: int = 150, pause: float = 0.5, workers: int = 8) -> dict[str, dict]:
    """Cotización de cierre de cada valor.

    Primero el endpoint de cotizaciones por lotes (rápido, pero a veces exige una sesión que Yahoo
    rechaza con 401); si falla, los metadatos del gráfico de cada valor, en paralelo.
    """
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone

    from yfinance.data import YfData

    yd = YfData()
    try:
        out = _quotes_v7(yd, symbols, chunk, pause)
        if out:
            return out
    except Exception as exc:  # noqa: BLE001
        log.warning("cotizaciones por lotes no disponibles (%s); se usan los metadatos del gráfico", exc)
    now_ts = datetime.now(timezone.utc).timestamp()

    def one(sym):
        for attempt in range(2):
            try:
                return sym, _quote_v8(yd, sym, now_ts)
            except Exception:  # noqa: BLE001
                time.sleep(1 + attempt)
        return sym, None

    with ThreadPoolExecutor(workers) as ex:
        res = dict(ex.map(one, symbols))
    out = {s: q for s, q in res.items() if q}
    log.info("cotizaciones por gráfico: %d de %d", len(out), len(symbols))
    return out


def patch_from_quotes(data: dict, quotes: dict, mc: dict, now_utc=None) -> list[str]:
    """Añade la última sesión cerrada cuando la serie diaria de Yahoo aún no la trae.

    Tras el cierre, Yahoo publica la fila del día con apertura, máximo, mínimo y volumen pero
    con el cierre vacío durante horas (EE. UU. y Europa); la descarga la descarta. La cotización
    de cierre del mismo día (precio, máximo, mínimo, apertura y volumen de la sesión regular)
    la completa. No se toca nada si el mercado sigue abierto.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    now_utc = now_utc or datetime.now(timezone.utc)
    patched = []
    for sym, df in data.items():
        q = quotes.get(sym)
        if q is None or df is None or not len(df) or sym.endswith("=X"):
            continue
        if q.get("marketState") == "REGULAR":
            continue
        t, px = q.get("regularMarketTime"), q.get("regularMarketPrice")
        if not t or not px or px <= 0 or now_utc.timestamp() - t < 15 * 60:
            continue
        hi, lo = q.get("regularMarketDayHigh") or 0, q.get("regularMarketDayLow") or 0
        if hi <= 0 or lo <= 0:
            if not sym.startswith("^"):
                continue
            hi = lo = px  # índices sin rango intradía: solo se usa el cierre
        tzname = q.get("exchangeTimezoneName") or mc["by_suffix"].get(market_of(sym, mc), mc["default"])[0]
        day = datetime.fromtimestamp(t, ZoneInfo(tzname)).date()
        last = pd.Timestamp(df.index[-1])
        if day <= last.date():
            continue
        op = q.get("regularMarketOpen")
        row = {"Open": op if op and op > 0 else float("nan"), "High": max(hi, px), "Low": min(lo, px), "Close": px,
               "Volume": float(q.get("regularMarketVolume") or 0)}
        if "Adj Close" in df.columns:
            row["Adj Close"] = px
        idx = pd.DatetimeIndex([pd.Timestamp(day)], tz=last.tz, name=df.index.name)
        data[sym] = pd.concat([df, pd.DataFrame([{c: row.get(c, float("nan")) for c in df.columns}], index=idx)])
        patched.append(sym)
    return patched


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


def last_dates(data: dict, mc: dict) -> str:
    """Resumen para el registro: fecha más reciente y número de valores que la tienen, por mercado."""
    groups: dict[str, dict] = {}
    for sym, df in data.items():
        if sym.endswith("=X") or sym.startswith("^") or df is None or not len(df):
            continue
        g = groups.setdefault(market_of(sym, mc) or "US", {})
        d = pd.Timestamp(df.index[-1]).date()
        g[d] = g.get(d, 0) + 1
    parts = []
    for k in sorted(groups):
        top = max(groups[k])
        parts.append(f"{k} {top} ({groups[k][top]}/{sum(groups[k].values())})")
    return "; ".join(parts)


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
