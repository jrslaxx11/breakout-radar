"""Perfiles (sector/industria), capitalización y fechas de resultados, con caché en disco."""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .config import CACHE_DIR

log = logging.getLogger(__name__)
PROFILE_CACHE = CACHE_DIR / "profiles.json"


def _load(path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True))


def profiles(symbols: list[str], limit: int) -> dict[str, dict]:
    """Sector, industria y país. Solo descarga los que no están en caché (máx. `limit` por ejecución)."""
    import yfinance as yf

    cache = _load(PROFILE_CACHE)
    todo = [s for s in symbols if s not in cache][:limit]
    for s in todo:
        try:
            info = yf.Ticker(s).info or {}
            cache[s] = {
                "name": info.get("longName") or info.get("shortName") or "",
                "sector": info.get("sector") or "",
                "industry": info.get("industry") or "",
                "country": info.get("country") or "",
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("perfil %s: %s", s, exc)
        time.sleep(0.3)
    if todo:
        _save(PROFILE_CACHE, cache)
    return cache


def _to_dt(ts) -> datetime | None:
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return t.to_pydatetime()
    except Exception:  # noqa: BLE001
        return None


def details(symbols: list[str]) -> dict[str, dict]:
    """Capitalización, divisa, bolsa, país y resultados (último y próximo) de las candidatas finales."""
    import yfinance as yf

    out: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    for s in symbols:
        d: dict = {}
        try:
            tk = yf.Ticker(s)
            info = tk.info or {}
            d.update({
                "name": info.get("longName") or info.get("shortName") or "",
                "mcap": info.get("marketCap"),
                "currency": info.get("currency"),
                "exchange": info.get("fullExchangeName") or info.get("exchange"),
                "country": info.get("country") or "",
                "industry": info.get("industry") or "",
                "tz": info.get("exchangeTimezoneName") or "America/New_York",
            })
            last, nxt, est = None, None, info.get("isEarningsDateEstimate")
            # 1) fechas con hora (permiten saber si fue antes o después del cierre)
            try:
                ed = tk.get_earnings_dates(limit=8)
                if ed is not None and len(ed):
                    stamps = sorted(_to_dt(x) for x in ed.index if _to_dt(x))
                    past = [x for x in stamps if x <= now]
                    fut = [x for x in stamps if x > now]
                    last = past[-1] if past else None
                    nxt = fut[0] if fut else None
            except Exception:  # noqa: BLE001
                pass
            # 2) marca de tiempo del perfil
            et = _to_dt(info.get("earningsTimestamp"))
            if et:
                if et <= now and (last is None or et > last):
                    last = et
                if et > now and (nxt is None or et < nxt):
                    nxt = et
            # 3) calendario (solo fecha)
            if nxt is None:
                try:
                    cal = tk.calendar or {}
                    dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
                    for x in dates or []:
                        dx = _to_dt(pd.Timestamp(x))
                        if dx and dx.date() > now.date():
                            nxt, est = dx, True if est is None else est
                            break
                except Exception:  # noqa: BLE001
                    pass
            d["last_earnings"] = last.isoformat() if last else None
            d["next_earnings"] = nxt.date().isoformat() if nxt else None
            d["next_earnings_est"] = bool(est) if est is not None else None
        except Exception as exc:  # noqa: BLE001
            log.warning("detalles %s: %s", s, exc)
        out[s] = d
        time.sleep(0.4)
    return out


def earnings_reaction(df: pd.DataFrame, last_iso: str | None, tz_name: str = "America/New_York") -> dict | None:
    """Reacción del precio a los últimos resultados.

    Devuelve None si no hay fecha. `pending=True` si se publicaron tras el último cierre disponible.
    """
    if not last_iso:
        return None
    try:
        local = datetime.fromisoformat(last_iso).astimezone(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        return None
    day = local.date()
    amc = local.hour >= 15
    dates = [pd.Timestamp(x).date() for x in df.index]
    idx = next((i for i, d in enumerate(dates) if d >= day), None)
    if idx is None:
        return {"day": day.isoformat(), "amc": amc, "pending": True}
    if amc and dates[idx] == day:
        idx += 1
    if idx >= len(dates):
        return {"day": day.isoformat(), "amc": amc, "pending": True}
    c = df["Close"].to_numpy(dtype=float)
    o = df["Open"].to_numpy(dtype=float) if "Open" in df else c
    v = df["Volume"].fillna(0).to_numpy(dtype=float)
    e = len(c) - 1
    base_v = v[max(0, idx - 20):idx].mean() if idx > 0 else 0
    return {
        "day": day.isoformat(), "amc": amc, "pending": False, "sessions_ago": e - idx,
        "react": float(c[idx] / c[idx - 1] - 1), "gap": float(o[idx] / c[idx - 1] - 1),
        "since": float(c[e] / c[idx] - 1), "rvol": float(v[idx] / base_v) if base_v else None,
    }


def days_until(iso: str | None, today: date) -> int | None:
    if not iso:
        return None
    try:
        return (date.fromisoformat(iso) - today).days
    except ValueError:
        return None
