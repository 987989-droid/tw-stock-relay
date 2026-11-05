#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探測（2026/11/05）：「市場溫度計」候選資料源在 GitHub Actions 上是否可取得。
只記錄可得性與樣本，不判讀、不重試。輸出 data/selftest/market_probe.json。"""
import json, os, re, time, datetime, urllib.request, urllib.error

UA = "Mozilla/5.0 (tw-stock-relay probe)"
out = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "http": {}, "swagger": {}, "yf": {}}

def get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()

def sample(ct, b):
    t = b[:200000].decode("utf-8", "replace")
    try:
        j = json.loads(t)
        if isinstance(j, list):
            return {"type": "list", "len": len(j), "first": j[0] if j else None}
        if isinstance(j, dict):
            info = {"type": "dict", "keys": list(j)[:15]}
            for k in ("date", "title", "stat", "fields", "fields1"):
                if k in j: info[k] = j[k]
            for k in ("data", "tables"):
                if k in j and isinstance(j[k], list):
                    info[k + "_len"] = len(j[k]); info[k + "_first"] = j[k][0] if j[k] else None
            return info
    except Exception:
        pass
    return {"type": "text", "head": re.sub(r"\s+", " ", t[:400])}

def probe(name, url):
    time.sleep(1.5)
    try:
        st, ct, b = get(url)
        out["http"][name] = {"url": url, "status": st, "ct": ct, "bytes": len(b), "sample": sample(ct, b)}
    except urllib.error.HTTPError as e:
        out["http"][name] = {"url": url, "error": f"HTTP {e.code}"}
    except Exception as e:
        out["http"][name] = {"url": url, "error": repr(e)[:200]}

# 1) swagger 清單：找三大法人／融資券／外資持股／期貨法人相關路徑
for nm, url, pat in (("twse", "https://openapi.twse.com.tw/v1/swagger.json", r"fund|margin|QFII|BFI|T86|MI_"),
                     ("taifex", "https://openapi.taifex.com.tw/v1/swagger.json", r"Institutional|Insti|OpenInterest|LargeTraders")):
    try:
        st, ct, b = get(url)
        paths = list(json.loads(b).get("paths", {}))
        hit = [p for p in paths if re.search(pat, p, re.I)]
        out["swagger"][nm] = {"status": st, "paths_total": len(paths), "hits": hit[:40]}
        base = url.rsplit("/swagger.json", 1)[0]
        for p in hit[:12]:
            probe(f"{nm}_api{p}", base + p)
    except Exception as e:
        out["swagger"][nm] = {"error": repr(e)[:200]}

# 2) 證交所網站 rwd JSON（非 openapi）
for nm, url in (("twse_rwd_BFI82U", "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"),
                ("twse_rwd_T86", "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999"),
                ("twse_rwd_MI_MARGN", "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&selectType=MS"),
                ("twse_rwd_MI_QFIIS", "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?response=json&selectType=ALLBUT0999"),
                ("taifex_html_futContractsDate", "https://www.taifex.com.tw/cht/3/futContractsDate"),
                ("bot_rate_csv", "https://rate.bot.com.tw/xrt/flcsv/0/day")):
    probe(nm, url)

# 3) Yahoo（yfinance）：美股連動、風險情緒、匯率
try:
    import yfinance as yf
    for t in ("^SOX", "^IXIC", "TSM", "2330.TW", "^TWII", "^VIX", "^TNX", "TWD=X"):
        try:
            h = yf.Ticker(t).history(period="10d", auto_adjust=False)
            out["yf"][t] = {"rows": len(h), "last_date": str(h.index[-1].date()) if len(h) else None,
                            "last_close": float(h["Close"].iloc[-1]) if len(h) else None}
        except Exception as e:
            out["yf"][t] = {"error": repr(e)[:200]}
        time.sleep(1)
except Exception as e:
    out["yf"]["_import"] = repr(e)[:200]

os.makedirs("data/selftest", exist_ok=True)
json.dump(out, open("data/selftest/market_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: (v.get("status"), v.get("error"), v.get("bytes")) for k, v in out["http"].items()}, ensure_ascii=False, indent=0))
print(json.dumps(out["swagger"], ensure_ascii=False)[:1500]); print(json.dumps(out["yf"], ensure_ascii=False))
