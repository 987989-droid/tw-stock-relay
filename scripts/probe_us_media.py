"""三大美媒（WSJ／Bloomberg／Reuters）可抓性探測（2026/11/17）。只記狀態碼、則數、前 3 則標題與時間，不存內文。"""
import json, re, urllib.request, urllib.error, datetime as dt, xml.etree.ElementTree as ET
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
C = {
 "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
 "wsj_business": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
 "wsj_tech": "https://feeds.a.dj.com/rss/RSSWSJD.xml",
 "wsj_gn": GN + "site:wsj.com+when:1d",
 "bbg_markets": "https://feeds.bloomberg.com/markets/news.rss",
 "bbg_tech": "https://feeds.bloomberg.com/technology/news.rss",
 "bbg_economics": "https://feeds.bloomberg.com/economics/news.rss",
 "bbg_gn": GN + "site:bloomberg.com+when:1d",
 "rtr_sitemap": "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml",
 "rtr_business_html": "https://www.reuters.com/business/",
 "rtr_gn": GN + "site:reuters.com+when:1d",
 "rtr_gn_markets": GN + "site:reuters.com/markets+when:1d",
}
out = {}
for k, u in C.items():
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30)
        b = r.read(); st = r.status
    except urllib.error.HTTPError as e:
        out[k] = {"status": e.code}; continue
    except Exception as e:
        out[k] = {"err": repr(e)[:120]}; continue
    items = []
    try:
        root = ET.fromstring(b)
        for it in root.iter():
            tag = it.tag.split('}')[-1]
            if tag in ("item", "url"):
                t = next((c.text for c in it.iter() if c.tag.split('}')[-1] == "title" and c.text), None)
                d = next((c.text for c in it.iter() if c.tag.split('}')[-1] in ("pubDate", "publication_date", "lastmod") and c.text), None)
                if t: items.append([t.strip()[:120], d])
    except ET.ParseError:
        items = [["(非 XML)", len(b)]]
    out[k] = {"status": st, "bytes": len(b), "n": len(items), "top3": items[:3]}
json.dump({"at": dt.datetime.utcnow().isoformat() + "Z", "r": out}, open("data/probe/us_media.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
