#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_feeds.py — RSS 來源候選探測器（只在 workflow_dispatch 手動觸發時執行）

為什麼需要這支：
  2026-09-07 實測，ctee（工商時報）在 Actions 端回 HTTP 403、
  chinatimes（中時財經即時）回 HTTP 404。要修就得知道「哪個網址在
  Actions 這個網路環境下真的通」，但：
    - Cowork 沙箱 bash 對這些網域一律 403 host_not_allowed
    - 使用者電腦端的 device_bash 走同一組 proxy，同樣 403（已實測）
  也就是說，**唯一能測到真相的網路只有 GitHub Actions 自己**。
  與其用猜的改 FEEDS，不如讓 Actions 跑一次探測、把硬證據寫成檔案。

輸出：data/feed_probe.json
  逐一記錄每個候選網址在每種 User-Agent 下的 status / content-type /
  bytes / 前 120 字元 / 是否像 RSS。讀取端據此決定要不要納入 FEEDS。

紀律：本檔只做探測與記錄，**不修改 FEEDS、不影響每日新聞產出**。
"""
import json, os, time, datetime
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = datetime.timezone(datetime.timedelta(hours=8))
TIMEOUT = 8

UA_BOT = "Mozilla/5.0 (compatible; tw-stock-relay/1.0)"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# (key, url, 是否兩種 UA 都測)
# 兩種 UA 都測 → 只給「目前已知被擋」的網域，用來分辨是 UA 問題還是 IP 問題。
CANDIDATES = [
    # ── 工商時報：目前 403，測 UA 是否為主因 ────────────────
    ("ctee_feed",          "https://ctee.com.tw/feed", True),
    ("ctee_rss",           "https://ctee.com.tw/rss", True),
    ("ctee_feed_rss2",     "https://ctee.com.tw/?feed=rss2", True),
    ("ctee_tech",          "https://ctee.com.tw/category/news/tech/feed", True),
    # ── 中時：目前 404，逐一試路徑 ──────────────────────────
    ("ct_realtime_fin",    "https://www.chinatimes.com/rss/realtimenews-finance.xml", True),
    ("ct_money",           "https://www.chinatimes.com/rss/money.xml", True),
    ("ct_finance",         "https://www.chinatimes.com/rss/finance.xml", False),
    ("ct_realtimenews",    "https://www.chinatimes.com/rss/realtimenews.xml", False),
    ("ct_chinatimes_xml",  "https://www.chinatimes.com/rss/chinatimes.xml", False),
    ("ct_syndication",     "https://www.chinatimes.com/syndication/rss", False),
    # ── 旺得富（中時集團財經站）────────────────────────────
    ("wantrich_fin",       "https://wantrich.chinatimes.com/rss/finance.xml", False),
    ("wantrich_feed",      "https://wantrich.chinatimes.com/feed", False),
    # ── 其他候選補位來源 ──────────────────────────────────
    ("ettoday_finance",    "https://feeds.feedburner.com/ettoday/finance", False),
    ("ltn_business",       "https://news.ltn.com.tw/rss/business.xml", False),
    ("ltn_ec_business",    "https://ec.ltn.com.tw/rss/business.xml", False),
    ("cnyes_tw_industry",  "https://news.cnyes.com/rss/v1/news/category/tw_industry", False),
    ("yahoo_tw_news",      "https://tw.stock.yahoo.com/rss?category=news", False),
    ("udn_stock_sub",      "https://money.udn.com/rssfeed/news/1001/5591/7307?ch=money", False),
]


def probe(url, ua):
    t0 = time.time()
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
    })
    try:
        r = urllib.request.urlopen(req, timeout=TIMEOUT)
        raw = r.read(4000)
        head = raw[:120].decode("utf-8", "replace")
        return {
            "ok": True, "status": r.status,
            "ctype": (r.headers.get("Content-Type") or "")[:60],
            "head": head,
            "looks_rss": ("<rss" in head.lower() or "<feed" in head.lower()
                          or "<?xml" in head.lower()),
            "elapsed": round(time.time() - t0, 2),
        }
    except urllib.error.HTTPError as e:
        return {"ok": False, "err": "HTTPError %s %s" % (e.code, e.reason),
                "elapsed": round(time.time() - t0, 2)}
    except urllib.error.URLError as e:
        return {"ok": False, "err": "URLError %s" % (e.reason,),
                "elapsed": round(time.time() - t0, 2)}
    except Exception as e:
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:120]),
                "elapsed": round(time.time() - t0, 2)}


def main():
    now = datetime.datetime.now(TZ)
    out = {
        "probed_at_taipei": now.isoformat(timespec="seconds"),
        "note": ("RSS 候選來源探測結果。此檔只記錄事實，不代表已納入 FEEDS。"
                 "looks_rss=true 且 status=200 才可考慮納入。"
                 "同一網址若 BOT 失敗、BROWSER 成功，代表對方以 User-Agent 阻擋；"
                 "兩者皆失敗代表是 IP／路徑問題，換 UA 無效。"),
        "ua": {"bot": UA_BOT, "browser": UA_BROWSER},
        "results": {},
    }
    usable = []
    for key, url, both in CANDIDATES:
        rec = {"url": url, "browser": probe(url, UA_BROWSER)}
        if both:
            rec["bot"] = probe(url, UA_BOT)
        out["results"][key] = rec
        b = rec["browser"]
        flag = "OK" if (b.get("ok") and b.get("looks_rss")) else "NO"
        if flag == "OK":
            usable.append(key)
        print("%-20s %s %s" % (key, flag, b.get("status") or b.get("err")))

    out["usable_with_browser_ua"] = usable
    out["usable_count"] = len(usable)
    dst = os.path.join(ROOT, "data", "feed_probe.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("可用候選 %d 支：%s" % (len(usable), ", ".join(usable)))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("probe_feeds failed (non-fatal): %r" % e)
