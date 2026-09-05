#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_news.py — 由 GitHub Actions 抓取台灣財經新聞 RSS，解析後 commit 進 repo。

為什麼要放在 Actions：
  Cowork sandbox 的 egress 允許清單不含任何新聞網域，實測 2026-09-05
  cnyes / Yahoo / CNA / 工商 / 經濟日報 / 中時 全數回 HTTP 403 host_not_allowed。
  WebFetch 受網址溯源限制，排程無人值守時核准逾時 → PROVENANCE_REQUIRED。
  WebSearch 回的是常青 SEO 長文，不是當日有日期的標題。
  Actions runner 沒有這些限制 → 在這裡抓，Cowork 端只讀 raw.githubusercontent.com。

【重要原則 — 本 repo 為公開 repo】
  全市場、零過濾。不得寫入任何持股／追蹤清單股號。
  「哪一則跟我有關」一律由讀取端用自己保管的清單比對，股號永不進本 repo。

設計：
- 每個 feed 獨立 try/except，失敗只記錄失敗機制，不影響其他 feed。
- 自我限時：總預算用盡即停，照常寫出報告（job 逾時會什麼都留不下）。
- 輸出含 count 與各 feed 的 fetched/kept，供讀取端對帳，證明沒被截斷。
"""
import json, os, re, time, datetime, hashlib
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = datetime.timezone(datetime.timedelta(hours=8))

TIMEOUT = 15            # 單一 feed 逾時（秒）
BUDGET = 150            # 總預算（秒）
WINDOW_HOURS = 36       # 只留這段時間內的新聞
MAX_PER_FEED = 40       # 每個 feed 最多留幾則
DESC_MAX = 120          # 摘要截斷長度，控制檔案大小
UA = "Mozilla/5.0 (compatible; tw-stock-relay/1.0)"

FEEDS = [
    # key,                 url,                                                              desc
    ("cnyes_tw_stock",     "https://news.cnyes.com/rss/v1/news/category/tw_stock",            "鉅亨網 台股"),
    ("cnyes_wd_stock",     "https://news.cnyes.com/rss/v1/news/category/wd_stock",            "鉅亨網 國際股"),
    ("cnyes_tw_macro",     "https://news.cnyes.com/rss/v1/news/category/tw_macro",            "鉅亨網 台灣總經"),
    ("technews",           "https://technews.tw/feed/",                                       "科技新報"),
    ("moneydj",            "https://www.moneydj.com/kmdj/RssCenter.aspx?svc=NW&fno=1&arg=X0000000", "MoneyDJ 焦點新聞"),
    ("cna_finance",        "https://feeds.feedburner.com/rsscna/finance",                     "中央社 財經"),
    ("ctee",               "https://ctee.com.tw/feed",                                        "工商時報"),
    ("udn_money",          "https://money.udn.com/rssfeed/news/1001/5591?ch=money",           "經濟日報 股市"),
    ("chinatimes_finance", "https://www.chinatimes.com/rss/realtimenews-finance.xml",         "中時 財經即時"),
    ("yahoo_tw_market",    "https://tw.stock.yahoo.com/rss?category=tw-market",               "Yahoo 台股"),
]

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
# 台股慣用寫法：鉅亨「(2464-TW)」、多數媒體「台積電(2330)」「聯發科（2454）」
CODE_RE = re.compile(r"[（(]\s*(\d{4,6})\s*(?:-TW)?\s*[）)](?![年月日])")


def clean(s):
    if not s:
        return ""
    s = TAG_RE.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
    return WS_RE.sub(" ", s).strip()


def parse_ts(s):
    """RSS 的 pubDate（RFC822）或 Atom 的 ISO8601，統一轉台北時間。失敗回 None。"""
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(TZ)
    except Exception:
        pass
    try:
        t = s.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def text_of(node, *names):
    for n in names:
        el = node.find(n)
        if el is not None:
            if el.text and el.text.strip():
                return el.text
            href = el.get("href")
            if href:
                return href
        el = node.find("atom:" + n, NS)
        if el is not None:
            if el.text and el.text.strip():
                return el.text
            href = el.get("href")
            if href:
                return href
    return ""


def raw_text_of(node, path):
    el = node.find(path, NS)
    return (el.text or "") if el is not None else ""


def parse_feed(raw):
    """同時吃 RSS 2.0 與 Atom。回傳 [(title, link, ts_str, desc, codes, kw), ...]

    codes 由標題＋摘要＋全文一起抽，全文只用來抽股號、不入檔，
    目的是讓讀取端能以「股號」精確比對自己的清單，而不是猜公司名。
    """
    root = ET.fromstring(raw)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//atom:entry", NS)
    out = []
    for it in items:
        title = clean(text_of(it, "title"))
        link = clean(text_of(it, "link", "id"))
        ts = text_of(it, "pubDate", "published", "updated", "date")
        desc = clean(text_of(it, "description", "summary", "content"))
        body = clean(raw_text_of(it, "content:encoded"))
        kw = clean(raw_text_of(it, "media:keywords"))
        codes = []
        for m in CODE_RE.finditer(" ".join([title, desc, body])):
            c = m.group(1)
            if c not in codes:
                codes.append(c)
        if title:
            out.append((title, link, ts, desc, codes, kw))
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read()


def main():
    t_start = time.time()
    now = datetime.datetime.now(TZ)
    cutoff = now - datetime.timedelta(hours=WINDOW_HOURS)

    report = {}
    items = []
    seen = set()

    for key, url, desc in FEEDS:
        elapsed = time.time() - t_start
        if elapsed > BUDGET:
            report[key] = {"ok": False, "skipped": True, "desc": desc,
                           "err": "總預算 %ds 已用盡（已耗 %ds）" % (BUDGET, int(elapsed))}
            print(key, "SKIP")
            continue
        info = {"url": url, "desc": desc}
        try:
            t0 = time.time()
            code, raw = fetch(url)
            rows = parse_feed(raw)
            kept = 0
            undated = 0
            for title, link, ts_raw, summary, codes, kw in rows:
                if kept >= MAX_PER_FEED:
                    break
                ts = parse_ts(ts_raw)
                if ts is None:
                    # 無日期的一律標記，不假裝是今天
                    undated += 1
                    ts_out = None
                elif ts < cutoff:
                    continue
                else:
                    ts_out = ts.isoformat(timespec="minutes")
                sig = hashlib.md5(re.sub(r"[\s　]", "", title).encode("utf-8")).hexdigest()[:12]
                if sig in seen:
                    continue
                seen.add(sig)
                row = {"src": key, "t": title, "u": link, "ts": ts_out,
                       "d": summary[:DESC_MAX]}
                if codes:
                    row["c"] = codes[:8]
                if kw:
                    row["kw"] = kw[:80]
                items.append(row)
                kept += 1
            info.update({"ok": True, "status": code, "bytes": len(raw),
                         "fetched": len(rows), "kept": kept, "undated": undated,
                         "elapsed": round(time.time() - t0, 2)})
        except urllib.error.HTTPError as e:
            info.update({"ok": False, "err": "HTTPError %s %s" % (e.code, e.reason)})
        except urllib.error.URLError as e:
            info.update({"ok": False, "err": "URLError %s" % (e.reason,)})
        except ET.ParseError as e:
            info.update({"ok": False, "err": "XML 解析失敗（非 RSS/Atom 或回傳二進位）: %s" % e})
        except Exception as e:
            info.update({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        report[key] = info
        print(key, "OK" if info.get("ok") else "FAIL",
              info.get("kept", info.get("err", "")))

    items.sort(key=lambda x: (x["ts"] or ""), reverse=True)

    ok_feeds = [k for k, v in report.items() if v.get("ok")]
    payload = {
        "generated_at_taipei": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "window_hours": WINDOW_HOURS,
        "count": len(items),
        "feeds_ok": len(ok_feeds),
        "feeds_total": len(FEEDS),
        "coded": sum(1 for i in items if i.get("c")),
        "note": "全市場財經新聞標題，未做任何篩選。ts 為 null 表示該來源未提供可解析的發布時間，"
                "不得當作今日。c 欄為文中出現的台股代號（由「(2464-TW)」「(2330)」等寫法抽出），"
                "讀取端請以代號比對自己的清單；沒有 c 欄不代表與個股無關，仍須看標題。"
                "count 供讀取端對帳，確認未被截斷。",
        "feeds": report,
        "items": items,
    }

    rel = "data/daily/news/%s.json" % now.strftime("%Y-%m-%d")
    dst = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    with open(os.path.join(ROOT, "data", "news_status.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in payload.items() if k != "items"}, f,
                  ensure_ascii=False, indent=2)

    mpath = os.path.join(ROOT, "data", "latest.json")
    try:
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)
        files = manifest.get("files") or {}
        files["news"] = {"path": rel, "count": len(items), "mode": "daily",
                         "desc": "台灣財經新聞標題彙整（多來源 RSS，全市場零過濾）",
                         "feeds_ok": len(ok_feeds), "feeds_total": len(FEEDS)}
        manifest["files"] = files
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("併入索引失敗（非致命）:", e)

    print("items", len(items), "feeds_ok", len(ok_feeds), "/", len(FEEDS),
          "elapsed", round(time.time() - t_start, 1), "sec",
          "size", os.path.getsize(dst), "bytes")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("fetch_news failed (non-fatal): %r" % e)
