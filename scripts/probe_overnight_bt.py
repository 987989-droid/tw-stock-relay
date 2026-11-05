#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性回測（2026/11/06）：美國同業「隔夜」報酬能解釋台股隔天多少？
台股第 t 日 vs 嚴格早於 t 的最近一個美股收盤日報酬。指標：
- r2_gap：對台股開盤跳空（開盤/前收−1）的解釋力（R²）
- r2_cc：對台股當日收盤報酬（收/前收−1）的解釋力
- big：美國同業 |報酬| ≥7% 的日子，台股同方向收盤的比率與平均報酬
- base_r2_cc：台股自己前一日報酬對當日報酬的 R²（對照組）
輸出 data/selftest/overnight_bt.json。只用公開股價，對照表與 attribution.py 相同。"""
import json, os
import pandas as pd, yfinance as yf

GROUPS = (("6239 2408 2344 3260 8299 4967", "MU"),
          ("3363 4979 3081 3163 6442 4977 3450", "MRVL AVGO"),
          ("3035 6643 3443 3661 5269 3529 6533", "AVGO NVDA"),
          ("3231 2382 2317 6669 2356 2376 3013 8210", "NVDA"),
          ("2330 3711 2449 6147 6239 6451 6770 2303", "TSM NVDA"),
          ("4958 2368 3037 8046 3189 2383 6274", "NVDA AVGO"),
          ("2308 3017 3324 2421 8996 1519 1513 1503 1514", "VRT ETN GEV"))
mk = {r["code"]: r.get("market") for r in json.load(open("data/derived/beta_alpha.json"))["rows"]}
pairs = []
for g, p in GROUPS:
    for c in g.split():
        for q in p.split():
            pairs.append((c, q))
pairs.append(("^TWII", "^SOX")); pairs.append(("^TWII", "TSM"))
us_t = sorted({q for _, q in pairs} | {"^SOX"})
tw_t = sorted({c for c, _ in pairs})
def tw_sym(c): return c if c.startswith("^") else c + (".TWO" if mk.get(c) == "otc" else ".TW")
ONLY = os.environ.get("ONLY", "").split()
if ONLY:
    pairs = [(c, q) for c, q in pairs if q in ONLY]
    us_t = sorted({q for _, q in pairs}); tw_t = sorted({c for c, _ in pairs})
US = yf.download(us_t, period="14mo", auto_adjust=True, progress=False, group_by="column")["Close"]
# 2026/11/06：VRT 在批次下載中整欄為空 → 逐檔補抓並記錄診斷
diag = {}
for q in us_t:
    n = int(US[q].dropna().shape[0]) if q in US.columns else 0
    if n < 120:
        h = yf.Ticker(q).history(period="14mo", auto_adjust=True)["Close"]
        h.index = h.index.tz_localize(None) if h.index.tz is not None else h.index
        US[q] = h.reindex(US.index.tz_localize(None) if US.index.tz is not None else US.index) if len(US.index) else h
        diag[q] = {"batch_rows": n, "single_rows": int(h.dropna().shape[0])}
TWd = yf.download([tw_sym(c) for c in tw_t], period="14mo", auto_adjust=True, progress=False, group_by="column")
out = {"diag_us": None, "pairs": [], "note": "R² 0.10 以上才算有實用解釋力；big 為 |美國同業|≥7% 的日子"}
for c, q in pairs:
    s = tw_sym(c)
    try:
        cl, op = TWd["Close"][s].dropna(), TWd["Open"][s].dropna()
        u = US[q].dropna().pct_change().dropna()
    except Exception as e:
        out["pairs"].append({"tw": c, "us": q, "err": repr(e)[:100]}); continue
    df = pd.DataFrame({"cc": cl.pct_change(), "gap": op / cl.shift(1) - 1, "prev": cl.pct_change().shift(1)}).dropna()
    df = df[df.index >= df.index[-1] - pd.Timedelta(days=365)]
    ui = u.index.tz_localize(None) if u.index.tz is not None else u.index
    u.index = ui
    di = df.index.tz_localize(None) if df.index.tz is not None else df.index
    df.index = di
    # 對每個台股日 t，取嚴格早於 t 的最近美股報酬
    pos = u.index.searchsorted(df.index, side="left") - 1
    ok = pos >= 0
    df = df[ok]; df["us"] = u.values[pos[ok]]
    if len(df) < 120:
        out["pairs"].append({"tw": c, "us": q, "err": f"n={len(df)}"}); continue
    r2 = lambda a, b: round(float(df[a].corr(df[b]) ** 2), 3)
    big = df[df["us"].abs() >= 0.07]
    rec = {"tw": c, "us": q, "n": int(len(df)), "r2_gap": r2("gap", "us"), "r2_cc": r2("cc", "us"),
           "base_r2_cc": r2("cc", "prev"), "beta_cc": round(float(df["cc"].cov(df["us"]) / df["us"].var()), 2),
           "n_big": int(len(big))}
    if len(big):
        rec["big_same_dir_pct"] = round(float(((big["cc"] * big["us"]) > 0).mean() * 100), 1)
        rec["big_avg_cc_pct_when_us_down"] = round(float(big[big["us"] < 0]["cc"].mean() * 100), 2) if (big["us"] < 0).any() else None
    out["pairs"].append(rec)
ok = [p for p in out["pairs"] if "r2_cc" in p]
out["summary"] = {"n_pairs": len(ok),
                  "median_r2_gap": round(float(pd.Series([p["r2_gap"] for p in ok]).median()), 3),
                  "median_r2_cc": round(float(pd.Series([p["r2_cc"] for p in ok]).median()), 3),
                  "median_base_r2_cc": round(float(pd.Series([p["base_r2_cc"] for p in ok]).median()), 3),
                  "pairs_r2_cc_ge_0.10": sum(p["r2_cc"] >= 0.10 for p in ok)}
out["diag_us"] = diag
os.makedirs("data/selftest", exist_ok=True)
json.dump(out, open("data/selftest/overnight_bt" + ("_" + "_".join(ONLY) if ONLY else "") + ".json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out["summary"], ensure_ascii=False))
