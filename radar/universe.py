"""Construcción del universo de acciones.

Cuatro fuentes:
  * S&P 500, S&P 400 y S&P 600 (Wikipedia, con clasificación GICS). Selección no sesgada.
  * Todas las acciones cotizadas en EE. UU. (directorio oficial de Nasdaq Trader: Nasdaq, NYSE,
    NYSE American y Arca) con liquidez suficiente: es el terreno de caza de Qullamaggie, que escanea
    todo el mercado, no un índice. El filtro de liquidez se recalcula una vez por semana.
  * Lista fija internacional (config/universe_intl.csv). Selección no sesgada.
  * Descubrimiento: valores con mayor subida en 52 semanas por mercado (screener de Yahoo).
    Sesgado hacia los ganadores: sirve para encontrar candidatas, no para medir amplitud.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from io import StringIO

import pandas as pd
import requests

from .config import CACHE_DIR, Config

log = logging.getLogger(__name__)

WIKI = {
    "SPX": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "MID": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "SML": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
UA = {"User-Agent": "breakout-radar/1.0 (personal research; github actions)"}
NASDAQ_TRADER = ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                 "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
# Instrumentos que no son acciones ordinarias (los ADR/ADS sí se mantienen: Qullamaggie también los opera).
# ADR/ADS de empresas extranjeras: el directorio de Nasdaq lo indica en el nombre del valor.
ADR_NAME = re.compile(r"depositary|\bADS\b|\bADR\b", re.I)
NOT_COMMON = re.compile(r"\b(warrants?|rights?|units?|preferred|preference|notes? due|debentures?|"
                        r"subordinated|perpetual|% (series|fixed|senior))\b", re.I)


def _read_wiki_table(url: str) -> pd.DataFrame:
    html = requests.get(url, headers=UA, timeout=30).text
    try:
        tables = pd.read_html(StringIO(html), attrs={"id": "constituents"})
    except ValueError:
        tables = []
    if not tables:
        tables = [t for t in pd.read_html(StringIO(html))
                  if any(str(c).strip().lower().startswith("symbol") for c in t.columns) and len(t) > 300]
    df = tables[0]
    df.columns = [str(c).strip() for c in df.columns]
    return df


def sp_constituents() -> pd.DataFrame:
    """Componentes del S&P 1500 con sector y subindustria GICS. Usa caché si Wikipedia falla."""
    cache = CACHE_DIR / "sp_constituents.csv"
    frames = []
    try:
        for idx, url in WIKI.items():
            df = _read_wiki_table(url)
            sym_col = next(c for c in df.columns if c.lower().startswith("symbol") or c.lower() == "ticker symbol")
            name_col = next(c for c in df.columns if c.lower() in ("security", "company"))
            sec_col = next(c for c in df.columns if "sector" in c.lower())
            sub_col = next(c for c in df.columns if "sub-industry" in c.lower() or "sub industry" in c.lower())
            out = pd.DataFrame({
                "symbol": df[sym_col].astype(str).str.strip().str.replace(".", "-", regex=False),
                "name": df[name_col].astype(str).str.strip(),
                "sector": df[sec_col].astype(str).str.strip(),
                "sub": df[sub_col].astype(str).str.strip(),
                "index": idx,
            })
            frames.append(out)
            time.sleep(1)
        all_df = pd.concat(frames).drop_duplicates("symbol", keep="first").reset_index(drop=True)
        if len(all_df) > 1200:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            all_df.to_csv(cache, index=False)
            return all_df
        raise RuntimeError(f"solo {len(all_df)} componentes")
    except Exception as exc:  # noqa: BLE001
        log.warning("Wikipedia no disponible (%s); uso caché", exc)
        if cache.exists():
            return pd.read_csv(cache)
        raise


def discovery(cfg: Config) -> list[dict]:
    """Ganadores de 52 semanas por mercado. Caché de 7 días para no saturar a Yahoo."""
    dcfg = cfg.settings.get("discovery", {})
    if not dcfg.get("enabled"):
        return []
    cache = CACHE_DIR / "discovery.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched"])
        if age.days < 7:
            return data["quotes"]
    try:
        import yfinance as yf
        from yfinance import EquityQuery
    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance sin screener (%s)", exc)
        return []

    found: list[dict] = []
    failures = 0
    for region, min_cap in dcfg["regions"].items():
        region = str(region)
        if failures >= 3:
            log.warning("screener: 3 mercados seguidos sin respuesta; se omite el resto")
            break
        ok_ex = set(dcfg["exchanges"].get(region, []))
        try:
            query = EquityQuery("and", [
                EquityQuery("eq", ["region", region]),
                EquityQuery("gt", ["intradaymarketcap", min_cap]),
            ])
        except Exception as exc:  # noqa: BLE001
            log.warning("screener %s: consulta no válida (%s)", region, exc)
            continue
        quotes = []
        for offset in range(0, dcfg.get("per_region", 150), 100):
            try:
                size = min(100, dcfg["per_region"] - offset)
                resp = yf.screen(query, offset=offset, size=size,
                                 sortField="fiftytwowkpercentchange", sortAsc=False)
                batch = resp.get("quotes", []) if isinstance(resp, dict) else []
            except Exception as exc:  # noqa: BLE001
                log.warning("screener %s falló: %s", region, exc)
                batch = []
            quotes += batch
            if len(batch) < 100:
                break
            time.sleep(1)
        failures = 0 if quotes else failures + 1
        for q in quotes:
            if ok_ex and q.get("exchange") not in ok_ex:
                continue
            found.append({
                "symbol": q.get("symbol"),
                "name": (q.get("longName") or q.get("shortName") or "").strip(),
                "region": region,
                "exchange": q.get("exchange"),
                "mcap": q.get("marketCap"),
                "currency": q.get("currency"),
            })
        time.sleep(1)
    if found:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "quotes": found}))
    elif cache.exists():
        return json.loads(cache.read_text())["quotes"]
    return found


def parse_symbol_directory(text: str, kind: str) -> list[dict]:
    """Acciones ordinarias (y ADR) de un archivo del directorio de Nasdaq Trader.

    kind="nasdaq": Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
    kind="other":  ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
    """
    lines = [x for x in text.splitlines() if x and not x.startswith("File Creation Time")]
    if not lines:
        return []
    head = lines[0].split("|")
    out = []
    for line in lines[1:]:
        row = dict(zip(head, line.split("|")))
        sym = (row.get("Symbol") if kind == "nasdaq" else row.get("ACT Symbol")) or ""
        name = row.get("Security Name", "")
        if row.get("Test Issue") != "N" or row.get("ETF") != "N" or not sym:
            continue
        if any(ch in sym for ch in "$+=^#*") or NOT_COMMON.search(name):
            continue
        exch = "Nasdaq" if kind == "nasdaq" else {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca",
                                                   "Z": "Cboe", "V": "IEX"}.get(row.get("Exchange", ""), "")
        out.append({"symbol": sym.replace(".", "-"), "name": name.split(" - ")[0].strip(), "exchange": exch,
                    "adr": bool(ADR_NAME.search(name))})
    return out


def us_listed() -> list[dict]:
    """Todas las acciones cotizadas en EE. UU. según el directorio oficial de Nasdaq Trader."""
    rows = []
    for url, kind in zip(NASDAQ_TRADER, ("nasdaq", "other")):
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        rows += parse_symbol_directory(r.text, kind)
    seen, out = set(), []
    for x in rows:
        if x["symbol"] not in seen:
            seen.add(x["symbol"])
            out.append(x)
    return out


def us_liquid(cfg: Config, download_fn=None, listed_fn=None) -> list[dict]:
    """Acciones de EE. UU. con liquidez suficiente (valor negociado y precio), con caché semanal.

    Una vez por semana descarga un mes de datos de todo el directorio y guarda las que pasan el filtro;
    el resto de días usa la lista guardada. Si algo falla, se queda con la última lista válida.
    """
    ucfg = cfg.settings.get("us_universe") or {}
    if not ucfg.get("enabled", True):
        return []
    cache = CACHE_DIR / "us_liquid.json"
    old = json.loads(cache.read_text()) if cache.exists() else None
    if old:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(old["fetched"])
        if age.days < ucfg.get("refresh_days", 7):
            return old["rows"]
    try:
        listed = (listed_fn or us_listed)()
        if len(listed) < 3000:
            raise RuntimeError(f"directorio incompleto ({len(listed)} valores)")
        if download_fn is None:
            from .prices import download as download_fn
        prices = download_fn([x["symbol"] for x in listed], 30, ucfg.get("chunk", 150), ucfg.get("pause_s", 1.0),
                             period="1mo")
        min_mdv, min_px = ucfg.get("min_mdv_usd", 5_000_000), ucfg.get("min_price_usd", 3)
        rows = []
        for x in listed:
            df = prices.get(x["symbol"])
            if df is None or len(df) < 10:
                continue
            dv = (df["Close"] * df["Volume"].fillna(0)).tail(20)
            mdv, px = float(dv.median()), float(df["Close"].iloc[-1])
            if mdv >= min_mdv and px >= min_px:
                rows.append({**x, "mdv": round(mdv)})
        if len(rows) < 1000:
            raise RuntimeError(f"solo {len(rows)} valores líquidos")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "listed": len(listed),
                                     "rows": rows}, ensure_ascii=False, separators=(",", ":")))
        log.info("universo EE. UU.: %d líquidos de %d cotizados", len(rows), len(listed))
        return rows
    except Exception as exc:  # noqa: BLE001
        log.warning("universo EE. UU. no actualizado (%s); se usa la última lista", exc)
        return old["rows"] if old else []


def build_universe(cfg: Config) -> dict[str, dict]:
    """Devuelve {ticker: info}. `unbiased` indica si el valor sirve para medir amplitud."""
    uni: dict[str, dict] = {}
    sp = sp_constituents()
    for r in sp.itertuples(index=False):
        uni[r.symbol] = {"source": r.index, "name": r.name, "gics_sector": r.sector,
                         "gics_sub": r.sub, "hint": "", "unbiased": True}
    for sym, hint in cfg.intl:
        if sym in uni:
            if hint:
                uni[sym]["hint"] = hint
            continue
        uni[sym] = {"source": "INTL", "name": "", "gics_sector": "", "gics_sub": "",
                    "hint": hint, "unbiased": True}
    # Listas fijas de temáticas: también son selección no sesgada.
    for key, t in cfg.theme_defs.items():
        for sym in t.get("tickers", []) or []:
            sym = str(sym)
            if sym not in uni:
                uni[sym] = {"source": "INTL", "name": "", "gics_sector": "", "gics_sub": "",
                            "hint": key, "unbiased": True}
    us_rows = us_liquid(cfg)
    if us_rows and any("adr" not in q for q in us_rows):
        # Caché anterior al campo "adr": se toma del directorio de Nasdaq (dos descargas pequeñas).
        try:
            flags = {x["symbol"]: x["adr"] for x in us_listed()}
            us_rows = [{**q, "adr": flags.get(q["symbol"])} for q in us_rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("directorio de Nasdaq no disponible para marcar ADR (%s)", exc)
    for q in us_rows:
        sym = q["symbol"]
        if sym not in uni:
            uni[sym] = {"source": "USA", "name": q.get("name", ""), "gics_sector": "", "gics_sub": "",
                        "hint": "", "unbiased": False, "adr": q.get("adr")}
    for sym, info in uni.items():
        if info["source"] in ("SPX", "MID", "SML"):
            info.setdefault("adr", False)
    for q in discovery(cfg):
        sym = q.get("symbol")
        if sym and sym not in uni:
            uni[sym] = {"source": "DISC", "name": q.get("name", ""), "gics_sector": "", "gics_sub": "",
                        "hint": "", "unbiased": False, "region": q.get("region")}
    for sym in cfg.mine:
        if sym in uni:
            uni[sym]["mine"] = True
        else:
            uni[sym] = {"source": "MINE", "name": "", "gics_sector": "", "gics_sub": "", "hint": "",
                        "unbiased": False, "mine": True}
    dups = cfg.duplicates()
    for sym, primary in dups.items():
        if sym in uni:
            uni[sym]["duplicate_of"] = primary
    return uni
