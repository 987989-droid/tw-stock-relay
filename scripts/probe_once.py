#!/usr/bin/env python3
# 一次性探測（2026/10/28）：抓 6414 樺漢 115/08 重大訊息列表，並取出含「樺成」之公告全文。
# 跑完即刪除本檔與 probe_once.yml；輸出寫 probe/（不碰 data/）。
import os, re, json, urllib.request, urllib.parse
BASE = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
def post(fields):
    req = urllib.request.Request(BASE, data=urllib.parse.urlencode(fields).encode(),
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode("utf-8", "replace")
os.makedirs("probe", exist_ok=True)
log = {}
st, html = post({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                 "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                 "co_id": "6414", "year": "115", "month": "08", "b_date": "", "e_date": ""})
open("probe/t05st01_6414_11508_list.html", "w", encoding="utf-8").write(html)
log["list"] = {"http": st, "bytes": len(html), "has_樺成": "樺成" in html}
# 逐列找 onclick 內的 document.fm_t05st01.<欄>.value='<值>' 組，取含「樺成」的那幾列
rows = re.split(r"<tr", html)
hits = []
for r in rows:
    if "樺成" not in r: continue
    kv = dict(re.findall(r"fm_t05st01\.(\w+)\.value\s*=\s*['\"]([^'\"]*)['\"]", r))
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r)).strip()[:300]
    hits.append({"row_text": text, "fields": kv})
log["hits"] = hits
for n, h in enumerate(hits):
    f = {"encodeURIComponent": "1", "step": "2", "firstin": "true", "off": "1",
         "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "co_id": "6414"}
    f.update(h["fields"]); f["step"] = "2"
    try:
        st2, d = post(f)
        open(f"probe/t05st01_6414_detail_{n}.html", "w", encoding="utf-8").write(d)
        h["detail"] = {"http": st2, "bytes": len(d)}
    except Exception as e:
        h["detail"] = {"err": repr(e)}
json.dump(log, open("probe/_probe_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(log, ensure_ascii=False)[:3000])
