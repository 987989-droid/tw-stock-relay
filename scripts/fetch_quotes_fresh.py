#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上市收盤價補新（2026/11/14 建）。只收全市場資料，不含任何持股或追蹤清單。

原因：TWSE OpenAPI STOCK_DAY_ALL 比實際晚一個交易日（quotes_listed 的 Date 固定比 quotes_otc 舊一日），
      讀取端拿到的上市收盤因此是「前一交易日」，晚間讀時更是兩個交易日前。
作法：向證交所 rwd MI_INDEX（指定日期查詢，回傳日期可驗證）取最新交易日的全部上市收盤；
      日期比現有 quotes_listed 新才改寫 data/latest/quotes_listed.json。
      欄位名與格式沿用 OpenAPI（Date 民國七碼、Code、Name、ClosingPrice…），讀取端不必改。
      同時更新 data/latest.json 的 files.quotes_listed（count、source、quote_date）。
紀律：回傳日期與請求日期不符、筆數不足、基準代號缺漏、與舊檔代號重疊率過低 → 整筆作廢、原檔不動；不重試。
用法：python scripts/fetch_quotes_fresh.py            正式（條件成立才改寫）
      python scripts/fetch_quotes_fresh.py --probe    只探測與對帳，結果寫 data/selftest/quotes_probe.json，不改任何資料檔
"""
import json, os, re, sys, time, datetime, urllib.request, urllib.parse

PROBE = "--probe" in sys.argv
UA = "Mozilla/5.0 (tw-stock-relay quotes_fresh)"
TZ = datetime.timezone(datetime.timedelta(hours=8))
now = datetime.datetime.now(TZ)
QPATH = "data/latest/quotes_listed.json"
IPATH = "data/latest.json"
MUST = ("2330", "0050", "2317")
out = {"run_at_taipei": now.isoformat(), "mode": "probe" if PROBE else "apply", "tries": [], "result": None}


def get_json(url):
    time.sleep(3)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def roc(ds):
    return "%d%s" % (int(ds[:4]) - 1911, ds[4:])


def clean(s):
    s = re.sub(r"<[^>]*>", "", str(s)).replace(",", "").strip()
    return "" if s in ("--", "---", "X", "") else s


def tables_of(j):
    """rwd 新格式為 tables[{title,fields,data}]；舊格式為 fieldsN／dataN。兩者都收。"""
    ts = []
    for t in j.get("tables") or []:
        if isinstance(t, dict) and t.get("fields") and t.get("data"):
            ts.append((t.get("title") or "", t["fields"], t["data"]))
    for k, v in j.items():
        m = re.fullmatch(r"fields(\d*)", k)
        if m and j.get("data" + m.group(1)):
            ts.append((j.get("subtitle" + m.group(1)) or k, v, j["data" + m.group(1)]))
    return ts


def parse(j, ds):
    best = None
    for title, fields, data in tables_of(j):
        f = [re.sub(r"<[^>]*>", "", str(x)).strip() for x in fields]
        if "證券代號" in f and "收盤價" in f and (best is None or len(data) > len(best[2])):
            best = (title, f, data)
    if not best:
        return None, "找不到含『證券代號』『收盤價』的表"
    title, f, data = best
    ix = {name: f.index(name) for name in f}
    need = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差"]
    miss = [n for n in need if n not in ix]
    if miss:
        return None, "缺欄位：%s（實際欄位 %s）" % (miss, f)
    sign_i = next((i for i, n in enumerate(f) if n.startswith("漲跌(")), None)
    rows = []
    for r in data:
        chg = clean(r[ix["漲跌價差"]])
        if chg:
            try:
                v = float(chg)
                sg = clean(r[sign_i]) if sign_i is not None else ""
                chg = "%.4f" % (-v if sg == "-" else v)
            except ValueError:
                chg = ""
        rows.append({
            "Date": roc(ds), "Code": clean(r[ix["證券代號"]]), "Name": str(r[ix["證券名稱"]]).strip(),
            "TradeVolume": clean(r[ix["成交股數"]]), "TradeValue": clean(r[ix["成交金額"]]),
            "OpeningPrice": clean(r[ix["開盤價"]]), "HighestPrice": clean(r[ix["最高價"]]),
            "LowestPrice": clean(r[ix["最低價"]]), "ClosingPrice": clean(r[ix["收盤價"]]),
            "Change": chg, "Transaction": clean(r[ix["成交筆數"]]),
        })
    return {"title": title, "fields": f, "rows": rows}, None


def fetch_day(ds):
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?" + urllib.parse.urlencode(
        {"response": "json", "date": ds, "type": "ALLBUT0999"})
    try:
        j = get_json(url)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)
    if j.get("stat") != "OK" or str(j.get("date")) != ds:
        return None, "無資料或日期不符（stat=%s date=%s）" % (j.get("stat"), j.get("date"))
    return parse(j, ds)


def finish(code=0):
    if PROBE:
        os.makedirs("data/selftest", exist_ok=True)
        json.dump(out, open("data/selftest/quotes_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        try:
            st = json.load(open("data/status.json", encoding="utf-8"))
            st.setdefault("sources", {})["quotes_listed_fresh"] = {
                "ok": out["result"] in ("replaced", "already_fresh"), "result": out["result"],
                "tries": out["tries"], "run_at_taipei": out["run_at_taipei"], "detail": out.get("detail")}
            json.dump(st, open("data/status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print("status.json 未更新：", e)
    print(json.dumps({k: v for k, v in out.items() if k != "samples"}, ensure_ascii=False))
    sys.exit(code)


old = json.load(open(QPATH, encoding="utf-8"))
old_date = max(str(x.get("Date", "")) for x in old)
old_codes = {str(x["Code"]).strip() for x in old}
out["openapi_date"] = old_date
out["openapi_count"] = len(old)

# 由今天往回找第一個有資料的交易日（最多回看 7 個日曆日，跳過週末）
got = None
for i in range(0, 8):
    d = now.date() - datetime.timedelta(days=i)
    if d.weekday() >= 5:
        continue
    ds = d.strftime("%Y%m%d")
    if roc(ds) <= old_date and not PROBE:
        out["tries"].append({"date": ds, "note": "不比現有檔新，停止"})
        break
    res, err = fetch_day(ds)
    out["tries"].append({"date": ds, "err": err, "rows": len(res["rows"]) if res else None})
    if res:
        got = (ds, res)
        break

if not got:
    out["result"] = "already_fresh" if (out["tries"] and out["tries"][-1].get("note")) else "no_data"
    finish(0)

ds, res = got
rows = res["rows"]
codes = {r["Code"] for r in rows}
overlap = len(codes & old_codes) / max(1, len(old_codes))
bad = []
if len(rows) < 0.9 * len(old):
    bad.append("筆數不足：%d（舊檔 %d）" % (len(rows), len(old)))
if [c for c in MUST if c not in codes]:
    bad.append("基準代號缺漏：%s" % [c for c in MUST if c not in codes])
if overlap < 0.95:
    bad.append("與舊檔代號重疊率 %.3f < 0.95" % overlap)
out["detail"] = {"date": ds, "roc": roc(ds), "rows": len(rows), "overlap": round(overlap, 4),
                 "table_title": res["title"], "fields": res["fields"]}

if PROBE:
    # 對帳：再抓「OpenAPI 現有那一天」的 MI_INDEX，逐檔比對收盤價，驗證欄位對應正確
    od = "%d%s" % (int(old_date[:-4]) + 1911, old_date[-4:])
    chk, err = fetch_day(od)
    if chk:
        m = {r["Code"]: r["ClosingPrice"] for r in chk["rows"]}
        diff, same, miss = [], 0, 0
        for x in old:
            c = str(x["Code"]).strip()
            a, b = str(x.get("ClosingPrice", "")).replace(",", "").strip(), m.get(c)
            if b is None:
                miss += 1
            elif (a == b) or (a and b and abs(float(a) - float(b)) < 1e-9):
                same += 1
            else:
                diff.append([c, a, b])
        out["reconcile"] = {"date": od, "same": same, "diff": len(diff), "missing_in_rwd": miss, "diff_sample": diff[:15]}
    else:
        out["reconcile"] = {"date": od, "err": err}
    pick = ("2330", "1519", "00878", "00940", "3231", "6239")
    out["samples"] = [r for r in rows if r["Code"] in pick]
    out["result"] = "probe_ok" if not bad else "probe_bad"
    out["bad"] = bad
    finish(0)

if bad:
    out["result"] = "rejected"
    out["bad"] = bad
    finish(0)
if roc(ds) <= old_date:
    out["result"] = "already_fresh"
    finish(0)

json.dump(rows, open(QPATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
idx = json.load(open(IPATH, encoding="utf-8"))
ent = idx.setdefault("files", {}).setdefault("quotes_listed", {"path": QPATH, "desc": "上市個股當日成交資訊", "mode": "latest_only"})
ent.update({"count": len(rows), "source": "twse_rwd_MI_INDEX", "quote_date": roc(ds), "openapi_date": old_date,
            "refreshed_at_taipei": now.isoformat()})
json.dump(idx, open(IPATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
out["result"] = "replaced"
finish(0)
