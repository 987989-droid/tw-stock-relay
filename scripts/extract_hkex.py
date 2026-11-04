"""港交所披露易：找最新業績公告 → 下載中文 PDF → pdftotext → 抽出含關鍵字的原文行。
只抽「原文行」不做數字解讀，供人工對帳後再決定正式抽數規則。輸出 data/selftest/hkex_extract.json。不重試。"""
import json, os, re, time, datetime, subprocess, tempfile, urllib.request, urllib.parse

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://www1.hkexnews.hk"
CO = {
    "騰訊": ("00700", ["資本開支"]),
    "阿里": ("09988", ["資本性支出", "資本開支"]),
    "百度": ("09888", ["資本開支"]),
    "中芯": ("00981", ["產能利用率", "利用率", "收入"]),
}
SKIP = re.compile(r"說明會|通知|日期|半年度報告|年度報告|海外監管|召開|預告|委任|股息")
HIT = re.compile(r"業績")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/search/titlesearch.xhtml"})
    time.sleep(1)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


today = datetime.date.today()
frm = (today - datetime.timedelta(days=150)).strftime("%Y%m%d")
out = {"run_at_utc": datetime.datetime.utcnow().isoformat(), "companies": {}}
for name, (sym, kws) in CO.items():
    rec = {}
    try:
        t = get(BASE + "/search/prefix.do?" + urllib.parse.urlencode(
            {"callback": "callback", "lang": "ZH", "type": "A", "name": sym, "market": "SEHK"})).decode("utf-8", "replace")
        sid = re.search(r'"stockId"\s*:\s*(\d+)\s*,\s*"code"\s*:\s*"' + sym + '"', t).group(1)
        q = {"sortDir": "0", "sortByOptions": "DateTime", "category": "0", "market": "SEHK", "stockId": sid,
             "documentType": "-1", "fromDate": frm, "toDate": today.strftime("%Y%m%d"), "title": "", "searchType": "0",
             "t1code": "-2", "t2Gcode": "-2", "t2code": "-2", "rowRange": "100", "lang": "zh"}
        j = json.loads(get(BASE + "/search/titleSearchServlet.do?" + urllib.parse.urlencode(q)))
        rows = json.loads(j["result"]) if isinstance(j["result"], str) else j["result"]
        cand = [r for r in rows if HIT.search(r.get("TITLE", "")) and not SKIP.search(r.get("TITLE", ""))
                and r.get("FILE_LINK", "").lower().endswith(".pdf")]
        if not cand:
            rec["error"] = "找不到業績公告"; out["companies"][name] = rec; continue
        r0 = cand[0]
        rec.update({"title": r0["TITLE"], "date": r0["DATE_TIME"], "link": BASE + r0["FILE_LINK"]})
        pdf = get(BASE + r0["FILE_LINK"])
        rec["pdf_bytes"] = len(pdf)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.pdf"); open(p, "wb").write(pdf)
            txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
        lines = txt.splitlines()
        rec["n_lines"] = len(lines)
        hits = []
        for i, ln in enumerate(lines):
            if any(k in ln for k in kws) and re.search(r"\d", ln):
                hits.append({"line": i, "text": re.sub(r"\s{2,}", "  ", ln.strip())[:220]})
        rec["hits"] = hits[:25]
    except Exception as e:
        rec["error"] = repr(e)[:300]
    out["companies"][name] = rec

os.makedirs("data/selftest", exist_ok=True)
with open("data/selftest/hkex_extract.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("title"), len(v.get("hits", [])), v.get("error")) for k, v in out["companies"].items()}, ensure_ascii=False))
