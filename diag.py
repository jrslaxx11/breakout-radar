import datetime as dt, json
from yfinance.data import YfData

yd = YfData()
U = lambda x: str(dt.datetime.fromtimestamp(x, dt.timezone.utc)) if x else None
print("ahora UTC", dt.datetime.now(dt.timezone.utc))
S = ["IQV", "AAPL", "RSP", "^GSPC", "^STOXX", "SAP.DE", "OR.PA", "MAERSK-B.CO", "7203.T", "CSL.AX", "REY.MI", "0700.HK", "005930.KS"]
print("\n== v8 última fila y meta")
for s in S:
    try:
        j = yd.get_raw_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{s}", params={"range": "5d", "interval": "1d"})
        r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]; m = r["meta"]
        last = {k: q[k][-1] for k in ("open", "high", "low", "close", "volume")}
        print(s, U(r["timestamp"][-1]), last, "| meta", U(m.get("regularMarketTime")), m.get("regularMarketPrice"),
              m.get("regularMarketDayHigh"), m.get("regularMarketDayLow"), m.get("regularMarketVolume"),
              "| periodo", U(m.get("currentTradingPeriod", {}).get("regular", {}).get("start")), U(m.get("currentTradingPeriod", {}).get("regular", {}).get("end")))
    except Exception as e:
        print(s, repr(e))
print("\n== v7 quote")
for host in ("query1", "query2"):
    try:
        j = yd.get_raw_json(f"https://{host}.finance.yahoo.com/v7/finance/quote", params={"symbols": ",".join(S)})
        for x in j["quoteResponse"]["result"]:
            print(host, x["symbol"], x.get("marketState"), U(x.get("regularMarketTime")), x.get("regularMarketOpen"), x.get("regularMarketDayHigh"),
                  x.get("regularMarketDayLow"), x.get("regularMarketPrice"), x.get("regularMarketVolume"), x.get("exchangeTimezoneName"))
        break
    except Exception as e:
        print(host, repr(e))
