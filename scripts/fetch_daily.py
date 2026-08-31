#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股資料中繼層 - 每日抓取

原則（不可違反）：
  1. 只抓取與落地，不做任何判讀、清洗、正規化
  2. 每個資料源獨立處理，失敗記錄後繼續，不中止、不重試、不換來源
  3. 失敗時絕不以前一日資料填補，該源標記為 failed
  4. 欄位原樣保存，不改名、不轉型（含上市上櫃欄位命名不一致處）
"""

import json
import os
import time
import datetime
import urllib.request

MAX_SECONDS = 90
MAX_BYTES = 30 * 1024 * 1024
CHUNK = 65536
UA = "Mozilla/5.0 (compatible; tw-relay/1.0)"

TWSE = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/openapi/v1"

# mode:
#   daily_keep    每日一檔、以日期命名、永久累積（不可回補者）
#   latest_only   只保留最新一份、每次覆蓋（可回補者）
#   monthly       以資料內的年月欄位命名，同月覆蓋
SOURCES = [
    # ---- 不可回補，永久累積 ----
    {"key": "material_listed", "mode": "daily_keep",
     "url": TWSE + "/opendata/t187ap04_L",
     "desc": "上市公司每日重大訊息"},
    {"key": "material_otc", "mode": "daily_keep",
     "url": TPEX + "/mopsfin_t187ap04_O",
     "desc": "上櫃公司每日重大訊息"},
    {"key": "insider_listed", "mode": "daily_keep",
     "url": TWSE + "/opendata/t187ap12_L",
     "desc": "上市內部人持股轉讓事前申報(轉讓)"},
    {"key": "insider_otc", "mode": "daily_keep",
     "url": TPEX + "/mopsfin_t187ap12_O",
     "desc": "上櫃內部人持股轉讓事前申報(轉讓) - 端點未經驗證"},

    # ---- 可回補，只留最新 ----
    {"key": "quotes_listed", "mode": "latest_only",
     "url": TWSE + "/exchangeReport/STOCK_DAY_ALL",
     "desc": "上市個股當日成交資訊"},
    {"key": "quotes_otc", "mode": "latest_only",
     "url": TPEX + "/tpex_mainboard_daily_close_quotes",
     "desc": "上櫃每日收盤行情"},
    {"key": "valuation_listed", "mode": "latest_only",
     "url": TWSE + "/exchangeReport/BWIBBU_ALL",
     "desc": "上市本益比/殖利率/股價淨值比"},

    # ---- 月更新，以資料年月命名 ----
    {"key": "revenue_listed", "mode": "monthly", "period_field": "資料年月",
     "url": TWSE + "/opendata/t187ap05_L",
     "desc": "上市公司每月營業收入彙總表"},
    {"key": "revenue_otc", "mode": "monthly", "period_field": "資料年月",
     "url": TPEX + "/mopsfin_t187ap05_O",
     "desc": "上櫃公司每月營業收入彙總表"},
    {"key": "revenue_emerging", "mode": "monthly", "period_field": "資料年月",
     "url": TPEX + "/t187ap05_R",
     "desc": "興櫃公司每月營業收入彙總表"},
    {"key": "pledge_listed", "mode": "monthly", "period_field": "資料年月",
     "url": TWSE + "/opendata/t187ap11_L",
     "desc": "上市公司董監事持股餘額明細(含設質)"},
    {"key": "pledge_otc", "mode": "monthly", "period_field": "資料年月",
     "url": TPEX + "/mopsfin_t187ap11_O",
     "desc": "上櫃公司董監事持股餘額明細(含設質) - 前次觀測為 HTTP 520"},
]


def taipei_now():
    return datetime.datetime.now(datetime.timezone(
        datetime.timedelta(hours=8)))


def fetch(url):
    """回傳 (raw_bytes, meta)。任何失敗都不拋出，寫在 meta['err']。"""
    meta = {"status": None, "bytes": 0, "elapsed": None,
            "truncated": False, "timed_out": False, "err": None}
    t0 = time.time()
    buf = bytearray()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            meta["status"] = r.status
            while True:
                if time.time() - t0 > MAX_SECONDS:
                    meta["timed_out"] = True
                    break
                if len(buf) >= MAX_BYTES:
                    meta["truncated"] = True
                    break
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                buf.extend(chunk)
    except Exception as e:
        meta["err"] = "%s: %s" % (type(e).__name__, e)
    meta["elapsed"] = round(time.time() - t0, 2)
    meta["bytes"] = len(buf)
    return bytes(buf), meta


def main():
    now = taipei_now()
    today = now.strftime("%Y-%m-%d")
    status = {
        "run_at_taipei": now.isoformat(),
        "date": today,
        "sources": {},
    }
    latest = {
        "generated_at_taipei": now.isoformat(),
        "date": today,
        "note": "資料原樣保存，未經正規化。上市與上櫃欄位命名不一致，判讀層需自行對應。",
        "files": {},
        "failed": [],
    }

    for src in SOURCES:
        key = src["key"]
        raw, meta = fetch(src["url"])

        entry = dict(meta)
        entry["url"] = src["url"]
        entry["desc"] = src["desc"]
        entry["count"] = None
        entry["path"] = None
        entry["ok"] = False

        # 判定是否為完整且可解析的 JSON list
        data = None
        if raw and not meta["err"] and not meta["truncated"] \
                and not meta["timed_out"]:
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(parsed, list):
                    data = parsed
                    entry["count"] = len(parsed)
                else:
                    entry["err"] = "回傳不是 list，型別=%s" % type(parsed).__name__
            except json.JSONDecodeError as e:
                entry["err"] = "JSON 解析失敗: %s" % e

        if data is None:
            # 失敗：不寫檔、不沿用舊資料
            status["sources"][key] = entry
            latest["failed"].append(key)
            print("FAIL %-18s status=%s bytes=%s sec=%s err=%s"
                  % (key, meta["status"], meta["bytes"],
                     meta["elapsed"], entry["err"]), flush=True)
            continue

        # 決定落點
        if src["mode"] == "daily_keep":
            path = "data/daily/%s/%s.json" % (key, today)
        elif src["mode"] == "latest_only":
            path = "data/latest/%s.json" % key
        else:  # monthly
            period = None
            if data and isinstance(data[0], dict):
                period = data[0].get(src["period_field"])
            if not period:
                period = "unknown-%s" % now.strftime("%Y%m")
                entry["err"] = "找不到 %s 欄位，改用執行年月命名" \
                    % src["period_field"]
            path = "data/monthly/%s/%s.json" % (key, period)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

        entry["path"] = path
        entry["ok"] = True
        entry["keys"] = list(data[0].keys()) if (
            data and isinstance(data[0], dict)) else None
        status["sources"][key] = entry
        latest["files"][key] = {
            "path": path,
            "count": entry["count"],
            "desc": src["desc"],
            "mode": src["mode"],
        }
        print("OK   %-18s count=%-7s sec=%-6s -> %s"
              % (key, entry["count"], meta["elapsed"], path), flush=True)

    os.makedirs("data", exist_ok=True)
    with open("data/status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in status["sources"].values() if v["ok"])
    print("")
    print("完成：成功 %d / 共 %d，失敗清單=%s"
          % (ok, len(SOURCES), latest["failed"]))
    # 即使有失敗也以 0 結束，讓後續 commit 步驟能把 status.json 存下來
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
