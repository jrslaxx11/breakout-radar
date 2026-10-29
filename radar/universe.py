"""Construcción del universo de acciones.

Tres fuentes:
  * S&P 500, S&P 400 y S&P 600 (Wikipedia, con clasificación GICS). Selección no sesgada.
  * Lista fija internacional (config/universe_intl.csv). Selección no sesgada.
  * Descubrimiento: valores con mayor subida en 52 semanas por mercado (screener de Yahoo).
    Sesgado hacia los ganadores: sirve para encontrar candidatas, no para medir amplitud.
"""
from __future__ import annotations

import json
import logging
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
    for region, min_cap in dcfg["regions"].items():
        ok_ex = set(dcfg["exchanges"].get(region, []))
        query = EquityQuery("and", [
            EquityQuery("eq", ["region", region]),
            EquityQuery("gt", ["intradaymarketcap", min_cap]),
        ])
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
    for q in discovery(cfg):
        sym = q.get("symbol")
        if sym and sym not in uni:
            uni[sym] = {"source": "DISC", "name": q.get("name", ""), "gics_sector": "", "gics_sub": "",
                        "hint": "", "unbiased": False, "region": q.get("region")}
    dups = cfg.duplicates()
    for sym, primary in dups.items():
        if sym in uni:
            uni[sym]["duplicate_of"] = primary
    return uni
