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

# 1c) GE Vernova 電網（Electrification 部門）訂單與積壓訂單句（2026/11/06 新增）
# 用途：宏觀 L2 電力段的北美電網設備需求一手指標，對照台股重電（華城等）月營收。
# 訂單為 MD&A 揭露（非 XBRL），故抽句不抽數；季度判讀時人工核對數字。
try:
    tick = json.loads(get("https://www.sec.gov/files/company_tickers.json", ua))
    gcik = next(v["cik_str"] for v in tick.values() if v["ticker"] == "GEV")
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{gcik:010d}.json", ua))["filings"]["recent"]
    i = next(k for k, f in enumerate(sub["form"]) if f in ("10-Q", "10-K"))
    url = f"https://www.sec.gov/Archives/edgar/data/{gcik}/{sub['accessionNumber'][i].replace('-', '')}/{sub['primaryDocument'][i]}"
    import html as _h2
    raw = get(url, ua).decode("utf-8", "replace")
    txt = re.sub(r"\s+", " ", _h2.unescape(re.sub(r"<[^>]+>", " ", raw)))
    sents = re.split(r"(?<=[.;])\s+", txt)
    keep = [x[:500] for x in sents if re.search(r"Electrification", x) and re.search(r"[Oo]rders|backlog|[Bb]acklog|remaining performance", x)]
    json.dump({"cik": gcik, "form": sub["form"][i], "url": url, "reportDate": sub["reportDate"][i], "sentences": keep[:40]},
              open(OUT + "/gev_grid.json", "w"), ensure_ascii=False, indent=1)
    status["gev_grid"] = f"ok {sub['form'][i]} {sub['reportDate'][i]} {len(keep)}"
except Exception as e:
    status["gev_grid"] = repr(e)[:300]

# 2) Federal Register：BIS 文件清單＋規則全文重點
try:
    q = [("conditions[agencies][]", "industry-and-security-bureau"),
         ("conditions[publication_date][gte]", (datetime.date.today() - datetime.timedelta(days=400)).isoformat()),
         ("per_page", "1000"), ("order", "newest")] + [("fields[]", f) for f in (
         "title", "type", "publication_date", "document_number", "action", "abstract", "raw_text_url", "effective_on")]
    d = json.loads(get("https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(q), "tw-stock-relay research"))
    res = d.get("results", [])
    rules = []
    for r in res:
        if r.get("type") != "Rule" or not r.get("raw_text_url"):
            continue
        rec = {k: r.get(k) for k in ("document_number", "publication_date", "effective_on", "title", "action", "abstract")}
        try:
            t = get(r["raw_text_url"], "tw-stock-relay research").decode("utf-8", "replace")
            flat = re.sub(r"\s+", " ", t)
            rec["chars"] = len(flat)
            rec["china_mentions"] = len(re.findall(r"China|Chinese|PRC|Hong Kong|Macau", flat))
            rec["entity_sentences"] = [x[:400] for x in re.findall(r"[^.]*\b(?:add(?:s|ing|ed)?|remov(?:es|ing|ed)|revis(?:es|ing|ed)|modif(?:ies|ying|ied))\b[^.]*\bentit(?:y|ies)\b[^.]*\.", flat)][:12]
            rec["country_counts"] = {c: len(re.findall(c, flat)) for c in ("China", "Russia", "Iran", "Hong Kong", "Taiwan", "United Arab Emirates", "Singapore", "Malaysia")}
            rec["semi_terms"] = {k: len(re.findall(k, flat, re.I)) for k in ("semiconductor", "advanced computing", "integrated circuit", "high bandwidth memory", "HBM", "polysilicon", "supercomputer", "artificial intelligence", "model weights")}
        except Exception as e:
            rec["text_error"] = repr(e)[:200]
        rules.append(rec)
    json.dump({"count": d.get("count"), "results": res}, open(OUT + "/fr_bis.json", "w"), ensure_ascii=False, indent=0)
    json.dump(rules, open(OUT + "/fr_rules.json", "w"), ensure_ascii=False, indent=1)
    status["fr_bis"] = f"ok {d.get('count')} rules {len(rules)}"
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

# 4) 台股組裝三家營運資金：已移至 scripts/tw_wc.py（獨立步驟，含快取與退避）


json.dump(status, open(OUT + "/status.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(status, ensure_ascii=False))
