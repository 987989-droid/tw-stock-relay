"""三大美媒產經頭條（2026/11/17 建）：WSJ、Bloomberg、Reuters 各取 10 則，只存標題、連結、時間、版別，不存內文。
管道（2026/11/17 於 Actions 實測）：
  Bloomberg：官方 RSS feeds.bloomberg.com（markets／technology／economics）200 且為當日新聞。
  WSJ：官方 RSS feeds.a.dj.com 回 200 但內容停在 2025/01（已停更），改用 Google News RSS 搜尋 site:wsj.com 各版。
  Reuters：官網與 sitemap 回 401（擋爬蟲），改用 Google News RSS 搜尋 site:reuters.com 各版。
「頭條」定義：各家財經相關版（市場、商業、科技、經濟）過去 24 小時內、去重後依發布時間由新到舊取前 10。
           無法取得各家編輯台的排序，故非「最重要」排名而是「最新」。
輸出：data/daily/us_media/<台北日期>.json；data/latest/us_media.json 為最新一份。失敗即停、不重試。
"""
import json, os, re, sys, urllib.request, urllib.parse, datetime as dt, email.utils, xml.etree.ElementTree as ET
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
def gn(q): return GN + urllib.parse.quote(q)
SRC = {
 "WSJ": [("市場", gn("site:wsj.com/finance when:1d")), ("商業", gn("site:wsj.com/business when:1d")),
         ("科技", gn("site:wsj.com/tech when:1d")), ("經濟", gn("site:wsj.com/economy when:1d"))],
 "Bloomberg": [("市場", "https://feeds.bloomberg.com/markets/news.rss"), ("科技", "https://feeds.bloomberg.com/technology/news.rss"),
               ("經濟", "https://feeds.bloomberg.com/economics/news.rss")],
 "Reuters": [("市場", gn("site:reuters.com/markets when:1d")), ("商業", gn("site:reuters.com/business when:1d")),
             ("科技", gn("site:reuters.com/technology when:1d"))],
}
SUFFIX = re.compile(r"\s+-\s+(WSJ|The Wall Street Journal|Bloomberg(\.com)?|Reuters)\s*$")
TZ = dt.timezone(dt.timedelta(hours=8))
now = dt.datetime.now(dt.timezone.utc)

def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30)
    return r.status, r.read()

out, status, ok_all = {}, {}, True
for media, secs in SRC.items():
    pool, seen = [], set()
    for sec, u in secs:
        try:
            st, b = get(u); root = ET.fromstring(b); n = 0
            for it in root.iter("item"):
                t = (it.findtext("title") or "").strip(); link = (it.findtext("link") or "").strip()
                pd = it.findtext("pubDate")
                try: ts = email.utils.parsedate_to_datetime(pd).astimezone(dt.timezone.utc)
                except Exception: ts = None
                if not t or ts is None or (now - ts).total_seconds() > 36 * 3600: continue
                t = SUFFIX.sub("", t); key = re.sub(r"\W+", "", t.lower())[:60]
                if key in seen: continue
                seen.add(key); n += 1
                pool.append({"t": t, "u": link, "ts": ts.astimezone(TZ).strftime("%m/%d %H:%M"), "_ts": ts.timestamp(), "sec": sec})
            status[f"{media}/{sec}"] = {"status": st, "kept": n}
        except Exception as e:
            status[f"{media}/{sec}"] = {"err": repr(e)[:120]}
    pool.sort(key=lambda x: -x["_ts"])
    top = [{k: v for k, v in x.items() if k != "_ts"} for x in pool[:10]]
    out[media] = top
    if len(top) < 10: ok_all = False
day = now.astimezone(TZ).strftime("%Y-%m-%d")
doc = {"generated_at_taipei": now.astimezone(TZ).strftime("%Y-%m-%d %H:%M"), "definition": "各家財經版過去36小時內去重後最新10則（非編輯台排名）",
       "media": out, "status": status, "complete": ok_all}
os.makedirs("data/daily/us_media", exist_ok=True); os.makedirs("data/latest", exist_ok=True)
for p in (f"data/daily/us_media/{day}.json", "data/latest/us_media.json"):
    json.dump(doc, open(p, "w"), ensure_ascii=False, indent=1)
print(json.dumps({m: len(v) for m, v in out.items()}), json.dumps(status, ensure_ascii=False))
sys.exit(0 if ok_all else 2)
