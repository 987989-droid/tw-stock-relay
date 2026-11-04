"""一次性探測：MOPS 抓指定公司兩季的資產負債表與綜合損益表，抽出應收帳款與營業收入列。
同時驗證歷史季別參數（isnew=false + year + season）。輸出 data/selftest/ar_probe.json。不重試。"""
import json, os, re, time, html, urllib.request, urllib.parse

CODES = ["2382", "2317", "3231"]
PERIODS = [("115", "2"), ("115", "1")]
BASE = "https://mopsov.twse.com.tw/mops/web/ajax_"
KEYS = re.compile(r"應收帳款|應付帳款|存貨|營業收入合計|營業收入淨額|銷貨收入淨額|^收入合計")
XBRL_RE = re.compile(r"CO_ID=(\d+)&SYEAR=(\d+)&SSEASON=(\d+)")


def fetch(table, co, y, s):
    body = urllib.parse.urlencode({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                                   "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
                                   "co_id": co, "year": y, "season": s}).encode()
    req = urllib.request.Request(BASE + table, data=body, headers={"User-Agent": "Mozilla/5.0",
                                                                  "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode("utf-8", "replace")


out = {}
for co in CODES:
    for y, s in PERIODS:
        for t in ("t164sb03", "t164sb04"):
            k = f"{co}_{y}Q{s}_{t}"
            rec = {}
            try:
                code, h = fetch(t, co, y, s)
                m = XBRL_RE.search(h)
                rec["http"] = code
                rec["meta"] = m.groups() if m else None
                hdr = re.search(r"<tr[^>]*>(.*?)</tr>", h[h.find("會計項目"):] if "會計項目" in h else "", re.S)
                rows = []
                for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
                    cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip()
                             for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
                    if cells and (KEYS.search(cells[0]) or "會計項目" in cells[0]):
                        rows.append(cells[:7])
                rec["rows"] = rows[:20]
            except Exception as e:
                rec["error"] = repr(e)[:200]
            out[k] = rec
            time.sleep(1.5)

os.makedirs("data/selftest", exist_ok=True)
json.dump(out, open("data/selftest/ar_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("http"), v.get("meta"), len(v.get("rows", [])), v.get("error")) for k, v in out.items()}, ensure_ascii=False))
