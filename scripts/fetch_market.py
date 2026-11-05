#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市場溫度計每日資料（2026/11/05 建）。只收全市場資料，不含任何持股或追蹤清單。
來源（2026/11/05 probe_market 實測可用）：
- 證交所 rwd JSON：BFI82U 三大法人買賣金額、MI_MARGN 信用交易統計、T86 三大法人個股買賣超（上市）
- Yahoo（yfinance）：^SOX ^IXIC TSM 2330.TW ^TWII ^VIX ^TNX TWD=X
輸出：data/derived/market_daily.json（history 依日期累積、thermo 為最新計算值）、
      data/derived/market_t86_<YYYYMMDD>.json（個股法人買賣超，最近 10 個交易日滾動保留）
紀律：單一來源失敗只記 status，不影響其他；回傳日期與請求日期不符者整筆作廢；不重試。"""
import json, os, glob, time, datetime, urllib.request, urllib.parse

OUT = "data/derived"
UA = "Mozilla/5.0 (tw-stock-relay market)"
TZ = datetime.timezone(datetime.timedelta(hours=8))
today = datetime.datetime.now(TZ).date()
status = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "twse": {}, "yf": {}}
P = os.path.join(OUT, "market_daily.json")
try:
    store = json.load(open(P, encoding="utf-8"))
except Exception:
    store = {"history": {}}
H = store.setdefault("history", {})

def get_json(url):
    time.sleep(3)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

num = lambda s: float(str(s).replace(",", "")) if str(s).strip() not in ("", "--") else None

# 需要抓的交易日：今天往回 14 個日曆日中，history 尚無證交所資料者（週末自動因 stat≠OK 略過）
days = [today - datetime.timedelta(days=i) for i in range(0, 15)]
todo = [d for d in days if d.weekday() < 5 and "foreign" not in H.get(d.strftime("%Y%m%d"), {}).get("bfi82u", {})]
for d in todo[:10]:
    ds = d.strftime("%Y%m%d")
    rec = H.setdefault(ds, {})
    try:
        j = get_json("https://www.twse.com.tw/rwd/zh/fund/BFI82U?" + urllib.parse.urlencode(
            {"response": "json", "type": "day", "dayDate": ds, "date": ds}))
        if j.get("stat") != "OK" or j.get("date") != ds:
            status["twse"][ds] = f"BFI82U 無資料或日期不符（stat={j.get('stat')} date={j.get('date')}）"
            if not rec: H.pop(ds, None)
            continue
        net = {}
        for row in j["data"]:
            name = row[0]
            v = num(row[3])
            if name.startswith("外資及陸資") and "不含" in name: net["foreign"] = v  # 「外資及陸資(不含外資自營商)」
            elif name.startswith("外資自營商"): net["foreign_dealer"] = v
            elif name.startswith("投信"): net["trust"] = v
            elif name.startswith("自營商(自行買賣)"): net["dealer_self"] = v
            elif name.startswith("自營商(避險)"): net["dealer_hedge"] = v
            elif name.startswith("合計"): net["total"] = v
        rec["bfi82u"] = net
        m = get_json("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?" + urllib.parse.urlencode(
            {"response": "json", "selectType": "MS", "date": ds}))
        if m.get("stat") == "OK" and m.get("date") == ds:
            for row in m["tables"][0]["data"]:
                if row[0].startswith("融資金額"):
                    rec["margin_amt_k"] = num(row[5]); rec["margin_amt_prev_k"] = num(row[4])
        t = get_json("https://www.twse.com.tw/rwd/zh/fund/T86?" + urllib.parse.urlencode(
            {"response": "json", "selectType": "ALLBUT0999", "date": ds}))
        if t.get("stat") == "OK" and t.get("date") == ds:
            f = t["fields"]
            iF, iT, iA = f.index("外陸資買賣超股數(不含外資自營商)"), f.index("投信買賣超股數"), f.index("三大法人買賣超股數")
            t86 = {r[0].strip(): [num(r[iF]), num(r[iT]), num(r[iA])] for r in t["data"]}
            json.dump({"date": ds, "fields": ["foreign", "trust", "total"], "unit": "股", "data": t86},
                      open(os.path.join(OUT, f"market_t86_{ds}.json"), "w", encoding="utf-8"), ensure_ascii=False)
            rec["t86_count"] = len(t86)
        status["twse"][ds] = "ok"
    except Exception as e:
        status["twse"][ds] = repr(e)[:200]

# 只保留最近 10 個 T86 檔
for f in sorted(glob.glob(os.path.join(OUT, "market_t86_*.json")))[:-10]:
    os.remove(f)

# Yahoo
YF = {}
try:
    import yfinance as yf
    for tk in ("^SOX", "^IXIC", "TSM", "2330.TW", "^TWII", "^VIX", "^TNX", "TWD=X"):
        try:
            h = yf.Ticker(tk).history(period="2mo", auto_adjust=False)
            YF[tk] = {str(i.date()): float(c) for i, c in h["Close"].items()}
            status["yf"][tk] = f"ok {len(YF[tk])}"
        except Exception as e:
            status["yf"][tk] = repr(e)[:150]
        time.sleep(1)
except Exception as e:
    status["yf"]["_import"] = repr(e)[:150]
store["yf_close"] = YF

def chg(tk, n):
    s = sorted(YF.get(tk, {}).items())
    if len(s) <= n: return None
    return round((s[-1][1] / s[-1 - n][1] - 1) * 100, 2), s[-1][0]

# 溫度計（最新）
td = sorted(k for k, v in H.items() if v.get("bfi82u"))
th = {"twse_last_date": td[-1] if td else None}
if td:
    last = H[td[-1]]["bfi82u"]
    th["foreign_net_today_e8"] = round(last.get("foreign", 0) / 1e8, 1)
    th["trust_net_today_e8"] = round(last.get("trust", 0) / 1e8, 1)
    for key in ("foreign", "trust"):
        sgn = 1 if (last.get(key) or 0) > 0 else -1
        streak = 0
        for d in reversed(td):
            v = H[d]["bfi82u"].get(key) or 0
            if (v > 0 and sgn > 0) or (v < 0 and sgn < 0): streak += 1
            else: break
        th[f"{key}_streak_days"] = streak * sgn  # 正＝連買、負＝連賣
        th[f"{key}_net_5d_e8"] = round(sum((H[d]["bfi82u"].get(key) or 0) for d in td[-5:]) / 1e8, 1)
    mm = [H[d].get("margin_amt_k") for d in td if H[d].get("margin_amt_k")]
    if len(mm) >= 2:
        th["margin_amt_e8"] = round(mm[-1] / 1e5, 1)
        th["margin_chg_5d_pct"] = round((mm[-1] / mm[-min(6, len(mm))] - 1) * 100, 2)
for tk, nm in (("^SOX", "sox"), ("^IXIC", "nasdaq"), ("^TWII", "twii"), ("TWD=X", "usdtwd"), ("^VIX", "vix")):
    for n in (1, 5):
        r = chg(tk, n)
        if r: th[f"{nm}_chg_{n}d_pct"], th[f"{nm}_date"] = r
if YF.get("^VIX"): th["vix"] = round(sorted(YF["^VIX"].items())[-1][1], 2)
if YF.get("^TNX"): th["us10y"] = round(sorted(YF["^TNX"].items())[-1][1], 3)
# 台積電 ADR 溢價：取 TSM、2330.TW、TWD=X 三者共同的最新日期
common = sorted(set(YF.get("TSM", {})) & set(YF.get("2330.TW", {})) & set(YF.get("TWD=X", {})))
if common:
    d = common[-1]
    adr = YF["TSM"][d] * YF["TWD=X"][d] / 5
    th["tsm_adr_premium_pct"] = round((adr / YF["2330.TW"][d] - 1) * 100, 2)
    th["tsm_adr_premium_date"] = d
store["thermo"] = th
store["status"] = status
os.makedirs(OUT, exist_ok=True)
json.dump(store, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(json.dumps({"thermo": th, "status": status}, ensure_ascii=False, indent=1))
