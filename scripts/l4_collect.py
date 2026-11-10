"""L4 政策地緣：中國商務部公告收集（2026/11/10 建）。
每週由 GitHub Actions 執行：抓商務部政務公開、首頁、產業安全與進出口管制局的公告連結，
篩出涉及出口管制／稀土／關鍵礦物／半導體／電池／實體清單／反傾銷等的項目，抓全文前 6000 字。
累積寫入 data/derived/l4_cn.json（以網址為鍵，記 first_seen）。只收集、不判讀。不重試。"""
import json, re, os, html, urllib.request, urllib.parse, datetime
UA = {"User-Agent": "Mozilla/5.0 (tw-stock-relay research)"}
OUT = "data/derived/l4_cn.json"
PAGES = {
    "政務公開": "https://www.mofcom.gov.cn/zwgk/index.html",
    "首頁": "https://www.mofcom.gov.cn/",
    "產業安全與進出口管制局": "http://aqygzj.mofcom.gov.cn/",
}
KW = re.compile(r"出口管制|两用物项|稀土|镓|锗|锑|钨|石墨|锂|电池|不可靠实体|管控名单|反倾销|反补贴|半导体|芯片|集成电路|技术目录|暂停|关税|实体清单|光伏|多晶硅")
NOW = datetime.datetime.now(datetime.timezone.utc)
def get(u, n=800000):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
        return r.geturl(), r.read(n).decode("utf-8", "ignore")
def text_of(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", t).strip()
db = {"items": {}}
if os.path.exists(OUT):
    try: db = json.load(open(OUT, encoding="utf-8"))
    except Exception: pass
items = db.setdefault("items", {})
log = {}
for name, u in PAGES.items():
    try:
        fu, h = get(u)
        n = 0
        for href, txt in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', h, re.S | re.I):
            title = html.unescape(re.sub(r"<[^>]+>", "", txt)).strip()
            if len(title) < 8 or not KW.search(title): continue
            link = urllib.parse.urljoin(fu, href)
            if "/art/" not in link: continue
            n += 1
            if link in items: continue
            it = {"title": title[:200], "source": name, "first_seen_utc": NOW.isoformat()}
            try:
                _, ah = get(link)
                body = text_of(ah)
                m = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", body)
                it["date_in_text"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
                i = body.find(title[:12])
                it["text"] = body[i if i > 0 else 0:][:6000]
            except Exception as e:
                it["fetch_error"] = repr(e)[:200]
            items[link] = it
        log[name] = {"ok": True, "matched_links": n}
    except Exception as e:
        log[name] = {"ok": False, "error": repr(e)[:200]}
db["generated_at_utc"] = NOW.isoformat()
db["last_run"] = log
db["item_count"] = len(items)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(db, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({"last_run": log, "item_count": len(items)}, ensure_ascii=False))
