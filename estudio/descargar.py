"""Descarga el histórico diario completo de una lista de tickers (estudio puntual, rama diag).

Uso: python estudio/descargar.py estudio/tickers.txt salida.npz
Guarda, por ticker, fechas (días desde 1970) y OHLCV en float32. Sin datos anteriores a 1970.
"""
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

FIELDS = ("Open", "High", "Low", "Close", "Volume")


def bajar(chunk):
    for intento in range(4):
        try:
            return yf.download(chunk, period="max", interval="1d", auto_adjust=False, actions=False,
                               group_by="ticker", threads=True, progress=False)
        except Exception as e:  # límite de peticiones u otro fallo temporal
            print("reintento", intento, type(e).__name__, e, flush=True)
            time.sleep(30 * (intento + 1))
    return None


def main(src, dst):
    tickers = [t.strip() for t in open(src) if t.strip()]
    out, sin_datos = {}, []
    for i in range(0, len(tickers), 8):
        chunk = tickers[i:i + 8]
        df = bajar(chunk)
        for t in chunk:
            try:
                sub = df[t] if df is not None else None
            except KeyError:
                sub = None
            if sub is None or sub.empty:
                sin_datos.append(t)
                continue
            sub = sub.dropna(subset=["High", "Low", "Close"])
            sub = sub[sub.index >= pd.Timestamp("1970-01-01")]
            if len(sub) < 60:
                sin_datos.append(t)
                continue
            d = (sub.index.tz_localize(None) if sub.index.tz is not None else sub.index)
            out[t + "|d"] = (d.values.astype("datetime64[D]").astype(np.int32))
            for f in FIELDS:
                col = sub[f] if f in sub else pd.Series(np.nan, index=sub.index)
                out[t + "|" + f[0]] = col.to_numpy(dtype=np.float32)
        print(f"{min(i + 8, len(tickers))}/{len(tickers)} · con datos {len(out) // 6}", flush=True)
        time.sleep(4)
    np.savez_compressed(dst, **out)
    print("con datos:", len(out) // 6, "· sin datos:", len(sin_datos))
    print("SIN DATOS:", " ".join(sin_datos))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
