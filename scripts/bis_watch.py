"""一次性監看：BIS「關係企業 50% 規則」暫停（2025-19846，原文寫明 2026/11/09 到期）是否有延長或後續規則。
查 Federal Register API：BIS 自 2026-10-01 起、全文含 affiliates 的文件。輸出 data/selftest/bis_watch.json。不重試。"""
import json, urllib.request, urllib.parse, datetime
out = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "query": "BIS, term=affiliates, since 2026-10-01"}
try:
    q = [("conditions[agencies][]", "industry-and-security-bureau"), ("conditions[term]", "affiliates"),
         ("conditions[publication_date][gte]", "2026-10-01"), ("per_page", "100"), ("order", "newest")] + \
        [("fields[]", f) for f in ("title", "type", "publication_date", "document_number", "abstract", "html_url", "effective_on")]
    req = urllib.request.Request("https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(q),
                                 headers={"User-Agent": "tw-stock-relay research"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    out["count"] = d.get("count")
    out["results"] = d.get("results", [])
    import re
    pat = re.compile(r"affiliates of certain listed entities|end-user controls|50 percent|fifty percent|2025-19846|2025-19001", re.I)
    out["relevant"] = [{k: r.get(k) for k in ("publication_date", "type", "title", "document_number", "html_url", "effective_on")}
                       | {"abstract": (r.get("abstract") or "")[:600]}
                       for r in out["results"] if pat.search(f"{r.get('title') or ''} {r.get('abstract') or ''}")]
    out["status"] = "ok"
except Exception as e:
    out["status"] = repr(e)[:300]
json.dump(out, open("data/selftest/bis_watch.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:1500])
