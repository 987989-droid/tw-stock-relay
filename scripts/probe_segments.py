"""探測：從 SEC 10-Q／10-K 的 inline XBRL 抽出「分部」營收與營業利益（companyfacts 不含維度資料）。
流程：data.sec.gov/submissions 找最近 3 份 10-Q/10-K → 下載主文件 htm → 解析 context 的
StatementBusinessSegmentsAxis 維度 → 取 Revenues／RevenueFromContract…／OperatingIncomeLoss 單季（約 3 個月）數字。
不預設分部名稱：所有分部成員一律輸出，由下游挑選。輸出 data/selftest/segments.json。不重試。"""
import json, os, re, time, html, datetime, urllib.request, urllib.error

CONTACT = os.environ.get("SEC_CONTACT", "").strip()
UA = f"tw-stock-relay research {CONTACT}"
CIKS = {"MSFT": 789019, "GOOGL": 1652044, "AMZN": 1018724, "META": 1326801, "NVDA": 1045810}
CONCEPTS = {"us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "us-gaap:OperatingIncomeLoss"}
AXIS = "us-gaap:StatementBusinessSegmentsAxis"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    time.sleep(0.5)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def contexts(doc):
    out = {}
    for m in re.finditer(r'<xbrli:context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</xbrli:context>', doc, re.S):
        cid, body = m.group(1), m.group(2)
        dims = re.findall(r'<xbrldi:explicitMember[^>]*dimension="([^"]+)"[^>]*>\s*([^<\s]+)\s*<', body)
        s = re.search(r"<xbrli:startDate>([^<]+)<", body)
        e = re.search(r"<xbrli:endDate>([^<]+)<", body)
        if not (s and e):
            continue
        out[cid] = {"dims": dims, "start": s.group(1).strip(), "end": e.group(1).strip()}
    return out


def facts(doc, ctx):
    rows = []
    for m in re.finditer(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", doc, re.S):
        attrs, inner = m.group(1), m.group(2)
        a = dict(re.findall(r'([\w:]+)="([^"]*)"', attrs))
        if a.get("name") not in CONCEPTS:
            continue
        c = ctx.get(a.get("contextRef"))
        if not c or len(c["dims"]) != 1 or c["dims"][0][0] != AXIS:
            continue
        d0 = datetime.date.fromisoformat(c["start"]); d1 = datetime.date.fromisoformat(c["end"])
        if not 80 <= (d1 - d0).days <= 100:  # 只取單季
            continue
        txt = re.sub(r"<[^>]+>", "", html.unescape(inner)).replace(",", "").strip()
        if not re.fullmatch(r"\d+(\.\d+)?", txt):
            continue
        val = float(txt) * (10 ** int(a.get("scale", "0")))
        if a.get("sign") == "-":
            val = -val
        rows.append({"concept": a["name"], "member": c["dims"][0][1], "start": c["start"], "end": c["end"], "val": val})
    seen, uniq = set(), []
    for r in rows:
        k = (r["concept"], r["member"], r["start"], r["end"])
        if k not in seen:
            seen.add(k); uniq.append(r)
    return uniq


out = {"run_at_utc": datetime.datetime.utcnow().isoformat(), "contact_declared": bool(CONTACT), "companies": {}}
for tk, cik in CIKS.items():
    rec = {"filings": [], "error": None}
    try:
        sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
        r = sub["filings"]["recent"]
        picks = [i for i, f in enumerate(r["form"]) if f in ("10-Q", "10-K")][:3]
        for i in picks:
            acc = r["accessionNumber"][i].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{r['primaryDocument'][i]}"
            f = {"form": r["form"][i], "reportDate": r["reportDate"][i], "filed": r["filingDate"][i], "url": url}
            try:
                doc = get(url).decode("utf-8", "replace")
                ctx = contexts(doc)
                f["n_contexts"] = len(ctx)
                f["facts"] = facts(doc, ctx)
            except Exception as e:
                f["error"] = repr(e)[:300]
            rec["filings"].append(f)
    except Exception as e:
        rec["error"] = repr(e)[:300]
    out["companies"][tk] = rec

os.makedirs("data/selftest", exist_ok=True)
with open("data/selftest/segments.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
for tk, rec in out["companies"].items():
    print(tk, rec["error"], [(f["reportDate"], len(f.get("facts", [])), f.get("error")) for f in rec["filings"]])
