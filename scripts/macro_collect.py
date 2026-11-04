"""宏觀專案基準期原料收集（只收原料，不判讀）。輸出 data/selftest/macro/：
- us_facts.json：五家 companyfacts 中 capex／毛利／營收標籤，end>=2024-01-01 的 10-Q/10-K 事實
- fr_bis.json：Federal Register API，BIS 2026-01-01 起文件清單（標題、類型、日期）
- hkex/<公司>_<日期>.txt：四家最近兩份單季業績公告全文（pdftotext -layout）
每段獨立 try，失敗記入 status.json，不重試。"""
import json, os, re, time, datetime, subprocess, tempfile, urllib.request, urllib.parse

OUT = "data/selftest/macro"
os.makedirs(OUT + "/hkex", exist_ok=True)
status = {"run_at_utc": datetime.datetime.utcnow().isoformat()}
CONTACT = os.environ.get("SEC_CONTACT", "").strip()


def get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    time.sleep(0.6)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


# 1) SEC companyfacts
try:
    ua = f"tw-stock-relay research {CONTACT}"
    CIKS = {"MSFT": 789019, "GOOGL": 1652044, "AMZN": 1018724, "META": 1326801, "NVDA": 1045810}
    TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "GrossProfit",
            "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "NetCashProvidedByUsedInOperatingActivities", "FinanceLeasePrincipalPayments",
            "FinanceLeaseRightOfUseAssetObtainedInExchangeForFinanceLeaseLiability",
            "RightOfUseAssetObtainedInExchangeForOperatingLeaseLiability",
            "RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability"]
    res = {}
    for tk, cik in CIKS.items():
        d = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", ua))
        g = d["facts"]["us-gaap"]
        res[tk] = {t: [{k: x.get(k) for k in ("start", "end", "val", "form", "fy", "fp", "filed", "accn")}
                       for x in g[t]["units"]["USD"] if x.get("form") in ("10-Q", "10-K") and x.get("end", "") >= "2024-01-01"]
                   for t in TAGS if t in g}
        if tk == "NVDA":  # 營業現金流拆解：淨利、調整項、營運資金變動、期末餘額
            res["NVDA_ocf_detail"] = {t: [{k: x.get(k) for k in ("start", "end", "val", "form", "filed")}
                                          for x in v["units"].get("USD", []) if x.get("form") in ("10-Q", "10-K") and x.get("end", "") >= "2025-01-01"]
                                      for t, v in g.items()
                                      if t.startswith("IncreaseDecrease") or t in ("NetIncomeLoss", "ShareBasedCompensation",
                                         "DepreciationDepletionAndAmortization", "AccountsReceivableNetCurrent", "InventoryNet",
                                         "DeferredIncomeTaxExpenseBenefit", "IncomeTaxesPaidNet")}
    json.dump(res, open(OUT + "/us_facts.json", "w"), indent=0)
    status["us_facts"] = "ok"
except Exception as e:
    status["us_facts"] = repr(e)[:300]

# 1b) NVDA 最新 10-Q 中提及應收帳款與客戶集中度的句子
try:
    import html as _h
    sub = json.loads(get("https://data.sec.gov/submissions/CIK0001045810.json", ua))["filings"]["recent"]
    i = next(k for k, f in enumerate(sub["form"]) if f == "10-Q")
    url = f"https://www.sec.gov/Archives/edgar/data/1045810/{sub['accessionNumber'][i].replace('-', '')}/{sub['primaryDocument'][i]}"
    raw = get(url, ua).decode("utf-8", "replace")
    txt = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", " ", raw)))
    sents = re.split(r"(?<=[.;])\s+", txt)
    keep = [x[:600] for x in sents if re.search(r"accounts receivable|Customer [A-Z]\b|direct customer|indirect customer", x, re.I)]
    json.dump({"url": url, "reportDate": sub["reportDate"][i], "sentences": keep[:80]}, open(OUT + "/nvda_ar.json", "w"), indent=1)
    status["nvda_ar"] = f"ok {len(keep)}"
except Exception as e:
    status["nvda_ar"] = repr(e)[:300]

# 2) Federal Register
try:
    q = [("conditions[agencies][]", "industry-and-security-bureau"), ("conditions[publication_date][gte]", (datetime.date.today() - datetime.timedelta(days=400)).isoformat()),
         ("per_page", "1000"), ("order", "newest")] + [("fields[]", f) for f in ("title", "type", "publication_date", "document_number", "action")]
    d = json.loads(get("https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(q), "tw-stock-relay research"))
    json.dump({"count": d.get("count"), "results": d.get("results", [])}, open(OUT + "/fr_bis.json", "w"), ensure_ascii=False, indent=0)
    status["fr_bis"] = f"ok {d.get('count')}"
except Exception as e:
    status["fr_bis"] = repr(e)[:300]

# 3) HKEX
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://www1.hkexnews.hk"
CO = {"tencent": "00700", "alibaba": "09988", "baidu": "09888", "smic": "00981"}
SKIP = re.compile(r"說明會|通知|日期|半年度報告|年度報告|海外監管|召開|預告|委任|股息|中期業績")
today = datetime.date.today()
status["hkex"] = {}
for name, sym in CO.items():
    try:
        t = get(BASE + "/search/prefix.do?" + urllib.parse.urlencode(
            {"callback": "callback", "lang": "ZH", "type": "A", "name": sym, "market": "SEHK"}), UA).decode("utf-8", "replace")
        sid = re.search(r'"stockId"\s*:\s*(\d+)\s*,\s*"code"\s*:\s*"' + sym + '"', t).group(1)
        q = {"sortDir": "0", "sortByOptions": "DateTime", "category": "0", "market": "SEHK", "stockId": sid, "documentType": "-1",
             "fromDate": (today - datetime.timedelta(days=270)).strftime("%Y%m%d"), "toDate": today.strftime("%Y%m%d"),
             "title": "", "searchType": "0", "t1code": "-2", "t2Gcode": "-2", "t2code": "-2", "rowRange": "200", "lang": "zh"}
        j = json.loads(get(BASE + "/search/titleSearchServlet.do?" + urllib.parse.urlencode(q), UA))
        rows = json.loads(j["result"]) if isinstance(j["result"], str) else j["result"]
        cand = [r for r in rows if "業績" in r.get("TITLE", "") and re.search(r"三個月|季度", r.get("TITLE", ""))
                and not SKIP.search(r.get("TITLE", "")) and r.get("FILE_LINK", "").lower().endswith(".pdf")]
        got = []
        for r in cand[:2]:
            pdf = get(BASE + r["FILE_LINK"], UA)
            with tempfile.TemporaryDirectory() as dd:
                p = os.path.join(dd, "a.pdf"); open(p, "wb").write(pdf)
                txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
            day = r["DATE_TIME"][:10].replace("/", "")
            fn = f"{OUT}/hkex/{name}_{day[4:]}{day[2:4]}{day[:2]}.txt"
            open(fn, "w", encoding="utf-8").write(f"# {r['TITLE']} | {r['DATE_TIME']} | {BASE + r['FILE_LINK']}\n" + txt)
            got.append({"title": r["TITLE"], "date": r["DATE_TIME"], "file": fn})
        status["hkex"][name] = got
    except Exception as e:
        status["hkex"][name] = repr(e)[:300]

# 4) 台股組裝三家營運資金（MOPS 最新一季與前一季的資產負債表、綜合損益表）
MOPS = "https://mopsov.twse.com.tw/mops/web/ajax_"
WC_KEYS = re.compile(r"應收帳款|應付帳款|^存貨$|營業收入合計")


def mops(table, co, isnew, y="", s=""):
    body = urllib.parse.urlencode({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "queryName": "co_id",
                                   "inpuType": "co_id", "TYPEK": "all", "isnew": isnew, "co_id": co, "year": y, "season": s}).encode()
    req = urllib.request.Request(MOPS + table, data=body, headers={"User-Agent": "Mozilla/5.0",
                                 "Content-Type": "application/x-www-form-urlencoded"})
    time.sleep(1.5)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def rows(h):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if cells and (WC_KEYS.search(cells[0]) or cells[0] == "會計項目"):
            out.append(cells[:7])
    return out


wc = {}
status["tw_wc"] = {}
for co in ["2382", "2317", "3231"]:
    try:
        h = mops("t164sb03", co, "true")
        m = re.search(r"CO_ID=(\d+)&SYEAR=(\d+)&SSEASON=(\d+)", h)
        if not m or m.group(1) != co:
            raise ValueError("代號或期別抽不到")
        y, q = int(m.group(2)) - 1911, int(m.group(3))
        periods = [(y, q)] + ([(y, q - 1)] if q > 1 else [])  # 跨年度 Q4 為全年報表，不取
        wc[co] = {}
        for (yy, qq) in periods:
            rec = {}
            for t in ("t164sb03", "t164sb04"):
                hh = h if (t == "t164sb03" and (yy, qq) == (y, q)) else mops(t, co, "false", str(yy), str(qq))
                mm = re.search(r"CO_ID=(\d+)&SYEAR=(\d+)&SSEASON=(\d+)", hh)
                if not mm or mm.group(1) != co or int(mm.group(2)) - 1911 != yy or int(mm.group(3)) != qq:
                    raise ValueError(f"{t} {yy}Q{qq} 回傳代號或期別不符")
                rec[t] = rows(hh)
            wc[co][f"{yy}Q{qq}"] = rec
        status["tw_wc"][co] = "ok " + ",".join(wc[co])
    except Exception as e:
        status["tw_wc"][co] = repr(e)[:200]
json.dump(wc, open(OUT + "/tw_wc.json", "w"), ensure_ascii=False, indent=0)

json.dump(status, open(OUT + "/status.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(status, ensure_ascii=False))
