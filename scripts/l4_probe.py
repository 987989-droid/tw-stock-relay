"""一次性探測（2026/11/10）：L4 政策地緣各國一手來源能否由 GitHub runner 自動抓取。
只記錄連線結果、頁面標題與含關鍵字的連結，不判讀。輸出 data/selftest/l4_probe.json。不重試。"""
import json, re, urllib.request, urllib.parse, datetime, html
UA = {"User-Agent": "Mozilla/5.0 (tw-stock-relay research probe)"}
KW = re.compile(r"出口管制|出口管制|两用物项|兩用|不可靠实体|反倾销|稀土|镓|锗|公告|戰略性高科技|輸出管制|安全保障貿易|輸出貿易管理|export control|semiconductor|半導体|半导体|exportcontrole|chip", re.I)
SRC = {
 "CN_mofcom_home": "https://www.mofcom.gov.cn/",
 "CN_mofcom_en": "https://english.mofcom.gov.cn/",
 "CN_mofcom_aqygzj": "http://aqygzj.mofcom.gov.cn/",
 "CN_mofcom_search_export_control": "https://www.mofcom.gov.cn/zwgk/index.html",
 "TW_trade_home": "https://www.trade.gov.tw/",
 "TW_trade_shtc": "https://www.trade.gov.tw/Pages/List.aspx?nodeID=1395",
 "JP_meti_press": "https://www.meti.go.jp/press/index.html",
 "JP_meti_en_press": "https://www.meti.go.jp/english/press/index.html",
 "NL_gov_exportcontrol": "https://www.government.nl/topics/export-controls-of-strategic-goods",
 "NL_rijksoverheid_exportcontrole": "https://www.rijksoverheid.nl/onderwerpen/exportcontrole-strategische-goederen",
}
def fetch(u, n=600000):
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read(n); return r.status, r.geturl(), b
out = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "sources": {}}
for k, u in SRC.items():
    d = {"url": u}
    try:
        st, fu, b = fetch(u)
        t = b.decode("utf-8", "ignore")
        m = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
        links = []
        for href, txt in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', t, re.S | re.I):
            txt = html.unescape(re.sub(r"<[^>]+>", "", txt)).strip()
            if txt and KW.search(txt):
                links.append([txt[:80], urllib.parse.urljoin(fu, href)])
        d.update(status=st, final_url=fu, bytes=len(b), title=(html.unescape(m.group(1)).strip()[:120] if m else None),
                 kw_links=links[:25])
    except Exception as e:
        d["error"] = repr(e)[:200]
    out["sources"][k] = d
# 美國 Federal Register：關稅／232／半導體（8/10 起），並試讀第一篇全文
try:
    q = [("conditions[term]", "semiconductor tariff OR section 232 semiconductors OR chips tariff"),
         ("conditions[publication_date][gte]", "2026-08-10"), ("per_page", "40"), ("order", "newest")] + \
        [("fields[]", f) for f in ("title", "type", "publication_date", "document_number", "agencies", "abstract", "html_url", "raw_text_url")]
    st, fu, b = fetch("https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(q))
    j = json.loads(b)
    res = [{"date": r.get("publication_date"), "type": r.get("type"), "no": r.get("document_number"),
            "agency": ",".join(a.get("name", "") for a in (r.get("agencies") or [])), "title": r.get("title"),
            "abstract": (r.get("abstract") or "")[:400], "html_url": r.get("html_url"), "raw_text_url": r.get("raw_text_url")}
           for r in j.get("results", [])]
    fr = {"status": st, "count": j.get("count"), "results": res}
    if res and res[0].get("raw_text_url"):
        try:
            st2, _, b2 = fetch(res[0]["raw_text_url"], 20000)
            fr["first_fulltext"] = {"status": st2, "head": re.sub(r"<[^>]+>", "", b2.decode("utf-8", "ignore"))[:3000]}
        except Exception as e:
            fr["first_fulltext"] = {"error": repr(e)[:200]}
    out["US_federal_register_tariff"] = fr
except Exception as e:
    out["US_federal_register_tariff"] = {"error": repr(e)[:200]}
json.dump(out, open("data/selftest/l4_probe.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("status"), v.get("error"), v.get("title")) for k, v in out["sources"].items()}, ensure_ascii=False))
