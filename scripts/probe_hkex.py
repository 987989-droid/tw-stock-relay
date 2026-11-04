"""探測：GitHub Actions runner 能否直接查港交所披露易，取得指定公司最新公告清單與 PDF。
步驟：(1) 抓一份已知 PDF 驗連線；(2) prefix.do 由股票代號查內部 stockId；(3) titleSearchServlet 查近 150 天公告。
端點與參數未經官方文件確認，本探測即為驗證；每步原樣記錄 HTTP 狀態與回應開頭。輸出 data/selftest/hkex_probe.json。不重試。"""
import json, os, re, time, datetime, urllib.request, urllib.parse

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KNOWN_PDF = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081200296.pdf"
CODES = {"騰訊": "00700", "阿里": "09988", "百度": "09888", "中芯": "00981"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml"})
    time.sleep(1)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:2000]
    except Exception as e:
        return None, repr(e).encode()


out = {"run_at_utc": datetime.datetime.utcnow().isoformat(), "known_pdf": {}, "companies": {}}
code, body = get(KNOWN_PDF)
out["known_pdf"] = {"http": code, "bytes": len(body), "is_pdf": body[:4] == b"%PDF"}

today = datetime.date.today()
frm = (today - datetime.timedelta(days=150)).strftime("%Y%m%d")
to = today.strftime("%Y%m%d")
for name, sym in CODES.items():
    rec = {}
    u = "https://www1.hkexnews.hk/search/prefix.do?" + urllib.parse.urlencode(
        {"callback": "callback", "lang": "ZH", "type": "A", "name": sym, "market": "SEHK"})
    c, b = get(u)
    txt = b.decode("utf-8", "replace")
    rec["prefix"] = {"http": c, "head": txt[:300]}
    m = re.search(r'"stockId"\s*:\s*(\d+)\s*,\s*"code"\s*:\s*"' + sym + '"', txt) or re.search(r'"stockId"\s*:\s*(\d+)', txt)
    if m:
        sid = m.group(1)
        rec["stockId"] = sid
        q = {"sortDir": "0", "sortByOptions": "DateTime", "category": "0", "market": "SEHK", "stockId": sid,
             "documentType": "-1", "fromDate": frm, "toDate": to, "title": "", "searchType": "0",
             "t1code": "-2", "t2Gcode": "-2", "t2code": "-2", "rowRange": "100", "lang": "zh"}
        c2, b2 = get("https://www1.hkexnews.hk/search/titleSearchServlet.do?" + urllib.parse.urlencode(q))
        t2 = b2.decode("utf-8", "replace")
        rec["search"] = {"http": c2, "bytes": len(b2), "head": t2[:300]}
        try:
            j = json.loads(t2)
            rows = json.loads(j.get("result", "[]")) if isinstance(j.get("result"), str) else j.get("result", [])
            rec["n_rows"] = len(rows)
            res = [r for r in rows if re.search(r"業績|業绩|results", (r.get("TITLE", "") + r.get("LONG_TEXT", "")), re.I)]
            rec["results_like"] = [{"date": r.get("DATE_TIME"), "title": r.get("TITLE"), "link": r.get("FILE_LINK")} for r in res[:5]]
        except Exception as e:
            rec["parse_error"] = repr(e)[:200]
    out["companies"][name] = rec

os.makedirs("data/selftest", exist_ok=True)
with open("data/selftest/hkex_probe.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:1500])
