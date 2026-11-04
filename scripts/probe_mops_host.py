"""一次性探測：備援站 mops.twse.com.tw 的舊 ajax 端點能否回傳與 mopsov 相同的財報表格（2317 115Q1 資產負債表）。"""
import json, re, urllib.request, urllib.parse, datetime
out = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
body = urllib.parse.urlencode({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "queryName": "co_id",
                               "inpuType": "co_id", "TYPEK": "all", "isnew": "false", "co_id": "2317", "year": "115", "season": "1"}).encode()
for host in ("https://mops.twse.com.tw/mops/web/ajax_t164sb03", "https://mopsov.twse.com.tw/mops/web/ajax_t164sb03"):
    rec = {}
    try:
        req = urllib.request.Request(host, data=body, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=60) as r:
            h = r.read().decode("utf-8", "replace"); rec["http"] = r.status; rec["final_url"] = r.geturl()
        m = re.search(r"CO_ID=(\d+)&SYEAR=(\d+)&SSEASON=(\d+)", h)
        rec.update({"bytes": len(h), "meta": m.groups() if m else None, "has_ar": "應收帳款淨額" in h,
                    "head": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))[:200]})
    except Exception as e:
        rec["error"] = repr(e)[:200]
    out[host.split("/")[2]] = rec
json.dump(out, open("data/selftest/mops_host_probe.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False))
