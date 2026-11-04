"""一次性探測：GitHub Actions runner 能否取得 SEC EDGAR 資料（data.sec.gov XBRL API 與 www.sec.gov 10-Q 全文）。
輸出 data/selftest/sec_probe.json。不重試；每個請求間隔 1 秒（SEC 公平存取上限為每秒 10 次）。"""
import json, time, urllib.request, urllib.error, datetime, os

UA = "tw-stock-relay research probe (https://github.com/987989-droid/tw-stock-relay)"
CIKS = {"MSFT": 789019, "GOOGL": 1652044, "AMZN": 1018724, "META": 1326801, "NVDA": 1045810}
TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
        "GrossProfit", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/0000789019/000119312526436133/msft-20260930.htm"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:4000]
    except Exception as e:
        return None, repr(e).encode()


out = {"run_at_utc": datetime.datetime.utcnow().isoformat(), "ua": UA, "companyfacts": {}, "archive": {}}
for tk, cik in CIKS.items():
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    code, body = get(url)
    rec = {"url": url, "http": code, "bytes": len(body)}
    if code == 200:
        d = json.loads(body)
        rec["entityName"] = d.get("entityName")
        g = d.get("facts", {}).get("us-gaap", {})
        rec["tags"] = {}
        for t in TAGS:
            if t not in g:
                continue
            usd = g[t].get("units", {}).get("USD", [])
            rows = [x for x in usd if x.get("form") in ("10-Q", "10-K")]
            rows.sort(key=lambda x: (x.get("filed", ""), x.get("end", "")))
            rec["tags"][t] = [{k: x.get(k) for k in ("start", "end", "val", "form", "fy", "fp", "filed")} for x in rows[-4:]]
    else:
        import re
        rec["error_text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.decode("utf-8", "replace")))[:1200]
    out["companyfacts"][tk] = rec
    time.sleep(1)

code, body = get(ARCHIVE)
out["archive"] = {"url": ARCHIVE, "http": code, "bytes": len(body),
                  "has_property_line": b"property and equipment" in body}

os.makedirs("data/selftest", exist_ok=True)
with open("data/selftest/sec_probe.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("http") if isinstance(v, dict) and "http" in v else {kk: vv.get("http") for kk, vv in v.items()}) for k, v in out.items() if k in ("companyfacts", "archive")}))
