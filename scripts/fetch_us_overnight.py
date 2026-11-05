#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股隔夜收盤（2026/11/06 建）：台北週二至週六 05:20 抓前一夜美股收盤，供 07:41 地雷監測溫度計使用。
只抓公開指數／個股收盤，不含任何持股。輸出 data/derived/us_overnight.json：
- latest：各代號最新收盤日、收盤、單日漲跌%
- tsm_adr：台積電 ADR 換算台幣隱含價（TSM×USD/TWD÷5）對台股 2330 最近收盤的差距%
- runs：每次實際執行時間（UTC），用來量 GitHub 排程準時率"""
import json, os, time, datetime

OUT = "data/derived/us_overnight.json"
TK = ["^SOX", "^IXIC", "NVDA", "AMD", "AVGO", "MU", "MRVL", "VRT", "TSM", "UMC", "ASX", "^VIX", "^TNX", "TWD=X", "2330.TW"]
try:
    store = json.load(open(OUT, encoding="utf-8"))
except Exception:
    store = {}
now = datetime.datetime.now(datetime.timezone.utc)
store.setdefault("runs", []).append(now.isoformat(timespec="seconds"))
store["runs"] = store["runs"][-60:]
latest, status = {}, {}
import yfinance as yf
for t in TK:
    try:
        h = yf.Ticker(t).history(period="10d", auto_adjust=False)["Close"].dropna()
        if len(h) >= 2:
            latest[t] = {"date": str(h.index[-1].date()), "close": round(float(h.iloc[-1]), 4),
                         "chg_1d_pct": round((float(h.iloc[-1]) / float(h.iloc[-2]) - 1) * 100, 2)}
            status[t] = "ok"
        else:
            status[t] = f"rows {len(h)}"
    except Exception as e:
        status[t] = repr(e)[:150]
    time.sleep(0.8)
adr = None
if all(k in latest for k in ("TSM", "TWD=X", "2330.TW")):
    implied = latest["TSM"]["close"] * latest["TWD=X"]["close"] / 5
    adr = {"tsm_date": latest["TSM"]["date"], "tw_date": latest["2330.TW"]["date"],
           "implied_twd": round(implied, 1), "tw_close": latest["2330.TW"]["close"],
           "gap_pct": round((implied / latest["2330.TW"]["close"] - 1) * 100, 2)}
store.update({"generated_at_utc": now.isoformat(timespec="seconds"), "latest": latest, "tsm_adr": adr, "status": status})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({"tsm_adr": adr, "status": status}, ensure_ascii=False))
