#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市場貝塔／阿法計算（GitHub Actions 中繼用，2026/10/28 建）。
- 對象：中繼 quotes_listed / quotes_otc 內全部 4 碼普通股代號（上市 .TW、上櫃 .TWO），
        刻意抓「全市場」而非追蹤清單，避免公開 repo 洩漏使用者的觀察名單。
- 資料：Yahoo Finance（yfinance，還原權息之調整收盤價），基準 ^TWII（加權指數）。
- 計算（近 250 個共同交易日之日簡單報酬，無風險利率取 0）：
    beta  = cov(r_i, r_m) / var(r_m)
    alpha = (mean(r_i) - beta*mean(r_m)) * 250        # 年化 Jensen's alpha（歷史值，非預測）
    r2    = corr^2；vol = std(r_i)*sqrt(250)
    ret_1m / ret_3m / ret_12m 與 rel_*（＝個股報酬 − 加權指數報酬）
- 寫入：data/derived/beta_alpha.json（每檔一列）、data/derived/_beta_status.json（抓取統計）。
- 紀律：單檔失敗不影響其他檔；不自動重試；樣本不足 120 日者不算 beta，只記錄。
"""
import json, os, re, datetime, math
import yfinance as yf
import pandas as pd

def codes(path, key):
    d = json.load(open(path, encoding="utf-8"))
    rows = d["data"] if isinstance(d, dict) and "data" in d else d
    return sorted({str(r[key]).strip() for r in rows if re.fullmatch(r"[1-9]\d{3}", str(r[key]).strip())})

idx = json.load(open("data/latest.json", encoding="utf-8"))["files"]
listed = codes(idx["quotes_listed"]["path"], "Code")
otc = codes(idx["quotes_otc"]["path"], "SecuritiesCompanyCode")
tick = {f"{c}.TW": (c, "listed") for c in listed}
tick.update({f"{c}.TWO": (c, "otc") for c in otc})

status = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "n_listed": len(listed), "n_otc": len(otc), "chunks": [], "ok": 0, "short": 0, "missing": 0}

mkt = yf.download("^TWII", period="14mo", interval="1d", auto_adjust=True, progress=False)["Close"]
if isinstance(mkt, pd.DataFrame):
    mkt = mkt.iloc[:, 0]
mkt = mkt.dropna()
status["twii_rows"] = int(len(mkt))
status["twii_last"] = str(mkt.index[-1].date()) if len(mkt) else None

closes = {}
names = list(tick)
for i in range(0, len(names), 200):
    chunk = names[i:i + 200]
    try:
        df = yf.download(chunk, period="14mo", interval="1d", auto_adjust=True,
                         progress=False, threads=True, group_by="column")["Close"]
        got = 0
        for t in chunk:
            if t in df.columns:
                s = df[t].dropna()
                if len(s):
                    closes[t] = s; got += 1
        status["chunks"].append({"from": i, "n": len(chunk), "got": got})
    except Exception as e:
        status["chunks"].append({"from": i, "n": len(chunk), "err": repr(e)[:300]})

def ret(s, n):
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None

m_ret = mkt.pct_change().dropna()
out = []
for t, (code, mk) in tick.items():
    s = closes.get(t)
    if s is None:
        status["missing"] += 1
        out.append({"code": code, "market": mk, "err": "no_data"}); continue
    r = s.pct_change().dropna()
    j = pd.concat([r, m_ret], axis=1, join="inner").dropna().iloc[-250:]
    j.columns = ["ri", "rm"]
    row = {"code": code, "market": mk, "n_days": int(len(j)),
           "last_date": str(s.index[-1].date()), "last_close": round(float(s.iloc[-1]), 2)}
    if len(j) < 120:
        status["short"] += 1; row["err"] = "short_history"; out.append(row); continue
    var_m = j["rm"].var()
    beta = j["ri"].cov(j["rm"]) / var_m
    alpha = (j["ri"].mean() - beta * j["rm"].mean()) * 250
    corr = j["ri"].corr(j["rm"])
    row.update({"beta": round(float(beta), 3), "alpha_ann": round(float(alpha), 4),
                "r2": round(float(corr * corr), 3),
                "vol_ann": round(float(j["ri"].std() * math.sqrt(250)), 4)})
    for k, n in (("1m", 21), ("3m", 63), ("12m", 250)):
        a, b = ret(s, n), ret(mkt, n)
        row[f"ret_{k}"] = round(a, 4) if a is not None else None
        row[f"rel_{k}"] = round(a - b, 4) if a is not None and b is not None else None
    status["ok"] += 1
    out.append(row)

os.makedirs("data/derived", exist_ok=True)
json.dump({"generated_at_utc": status["run_at_utc"], "benchmark": "^TWII",
           "window_days": 250, "rf": 0, "count": len(out), "rows": out},
          open("data/derived/beta_alpha.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(status, open("data/derived/_beta_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in status.items() if k != "chunks"}, ensure_ascii=False))
