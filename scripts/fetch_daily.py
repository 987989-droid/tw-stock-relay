
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股資料中繼層 - 每日抓取（v2）

原則（不可違反）：
  1. 只抓取與落地，不做任何判讀、清洗、正規化
  2. 失敗僅對「傳輸層」重試，最多 RETRY_MAX 次
     - 傳輸層失敗 = 連線例外 / 逾時 / 收到位元組數 < Content-Length
     - 資料層失敗 = 完整收到但 JSON 無法解析 -> 不重試
  3. 絕不換來源、絕不以前一日或任何替代資料填補
  4. 欄位原樣保存，不改名、不轉型
  5. 每次嘗試都記錄在 status.json 的 attempts 中

v2 相對 v1 的變更：
  - 月更新類先檢查目標年月檔案是否存在，已有則跳過（降低對來源的負載）
  - 各來源之間間隔 SLEEP_BETWEEN 秒
  - socket timeout 30 -> 60，單源總時間上限 90 -> 180
  - 以 Content-Length 判定下載完整性
  - 逾時/截斷會寫入 err 欄位（v1 漏寫，摘要看不出原因）
"""

import json
import os
import time
import datetime
import urllib.request

SOCKET_TIMEOUT = 60
MAX_SECONDS = 180
MAX_BYTES = 40 * 1024 * 1024
CHUNK = 65536
SLEEP_BETWEEN = 3
RETRY_MAX = 2
RETRY_WAIT = 10
UA = "Mozilla/5.0 (compatible; tw-relay/2.0)"

TWSE = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/openapi/v1"

# mode:
#   daily_keep    每日一檔、以日期命名、永久累積（不可回補者）
#   latest_only   只保留最新一份、每次覆蓋（可回補者）
#   monthly       以資料內的年月欄位命名；目標年月檔案已存在則跳過
SOURCES = [
    # ---- 不可回補，永久累積（優先，放最前面）----
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
     "desc": "上櫃內部人持股轉讓事前申報(轉讓)"},

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

    # ---- 月更新，多數日子會跳過 ----
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
     "desc": "上櫃公司董監事持股餘額明細(含設質)"},
]


def taipei_now():
    return datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8)))


def expected_period(now):
    """月更新資料的目標年月 = 上一個月，民國年月格式（例：11507）。"""
    y, m = now.year, now.month
    m -= 1
    if m == 0:
        m = 12
        y -= 1
    return "%d%02d" % (y - 1911, m)


def attempt_fetch(url):
    """單次嘗試。回傳 (raw_bytes, info)。任何失敗都不拋出。"""
    info = {"status": None, "bytes": 0, "content_length": None,
            "elapsed": None, "truncated": False, "timed_out": False,
            "incomplete": False, "err": None}
    t0 = time.time()
    buf = bytearray()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT) as r:
            info["status"] = r.status
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit():
                info["content_length"] = int(cl)
            while True:
                if time.time() - t0 > MAX_SECONDS:
                    info["timed_out"] = True
                    info["err"] = "總時間超過 %d 秒上限" % MAX_SECONDS
                    break
                if len(buf) >= MAX_BYTES:
                    info["truncated"] = True
                    info["err"] = "超過 %d bytes 上限" % MAX_BYTES
                    break
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                buf.extend(chunk)
    except Exception as e:
        info["err"] = "%s: %s" % (type(e).__name__, e)

    info["elapsed"] = round(time.time() - t0, 2)
    info["bytes"] = len(buf)

    if (info["content_length"] is not None
            and not info["truncated"]
            and info["bytes"] < info["content_length"]):
        info["incomplete"] = True
        info["err"] = "傳輸不完整：收到 %d / 應為 %d bytes" % (
            info["bytes"], info["content_length"])

    return bytes(buf), info


def transport_failed(info):
    """是否為傳輸層失敗（可重試）。"""
    return bool(info["err"]) or info["incomplete"] or info["timed_out"]


def fetch_with_retry(url):
    """回傳 (data_or_None, attempts, final_info, data_err)。"""
    attempts = []
    for i in range(RETRY_MAX + 1):
        if i > 0:
            time.sleep(RETRY_WAIT)
        raw, info = attempt_fetch(url)
        info["attempt"] = i + 1
        attempts.append(info)

        if transport_failed(info):
            continue

        # 傳輸成功，檢查資料本身。解析失敗不重試。
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            return None, attempts, info, "JSON 解析失敗: %s" % e
        if not isinstance(parsed, list):
            return None, attempts, info, "回傳不是 list，型別=%s" % type(
                parsed).__name__
        return parsed, attempts, info, None

    return None, attempts, attempts[-1], None


def main():
    now = taipei_now()
    today = now.strftime("%Y-%m-%d")
    period = expected_period(now)

    status = {"run_at_taipei": now.isoformat(), "date": today,
              "expected_period": period, "sources": {}}
    latest = {"generated_at_taipei": now.isoformat(), "date": today,
              "expected_period": period,
              "note": "資料原樣保存，未經正規化。上市與上櫃欄位命名不一致，"
                      "判讀層需自行對應。民國年月格式。",
              "files": {}, "failed": [], "skipped": []}

    first = True
    for src in SOURCES:
        key = src["key"]

        # 月更新類：目標年月已有檔案就跳過，不打擾來源
        if src["mode"] == "monthly":
            existing = "data/monthly/%s/%s.json" % (key, period)
            if os.path.exists(existing):
                status["sources"][key] = {
                    "ok": True, "skipped": True, "path": existing,
                    "desc": src["desc"],
                    "reason": "目標年月 %s 已存在" % period}
                latest["skipped"].append(key)
                latest["files"][key] = {"path": existing,
                                        "desc": src["desc"],
                                        "mode": "monthly",
                                        "count": None}
                print("SKIP %-18s %s" % (key, existing), flush=True)
                continue

        if not first:
            time.sleep(SLEEP_BETWEEN)
        first = False

        data, attempts, info, data_err = fetch_with_retry(src["url"])

        entry = {"ok": False, "skipped": False, "url": src["url"],
                 "desc": src["desc"], "mode": src["mode"],
                 "tries": len(attempts), "attempts": attempts,
                 "status": info.get("status"), "bytes": info.get("bytes"),
                 "elapsed": info.get("elapsed"),
                 "err": data_err or info.get("err"),
                 "count": None, "path": None, "keys": None}

        if data is None:
            status["sources"][key] = entry
            latest["failed"].append(key)
            print("FAIL %-18s tries=%d status=%s bytes=%s err=%s"
                  % (key, entry["tries"], entry["status"],
                     entry["bytes"], entry["err"]), flush=True)
            continue

        entry["count"] = len(data)

        if src["mode"] == "daily_keep":
            path = "data/daily/%s/%s.json" % (key, today)
        elif src["mode"] == "latest_only":
            path = "data/latest/%s.json" % key
        else:
            p = None
            if data and isinstance(data[0], dict):
                p = data[0].get(src["period_field"])
            if not p:
                p = "unknown-%s" % now.strftime("%Y%m")
                entry["err"] = "找不到 %s 欄位，改用執行年月命名" % src[
                    "period_field"]
            path = "data/monthly/%s/%s.json" % (key, p)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

        entry["ok"] = True
        entry["path"] = path
        entry["keys"] = list(data[0].keys()) if (
            data and isinstance(data[0], dict)) else None
        status["sources"][key] = entry
        latest["files"][key] = {"path": path, "count": entry["count"],
                                "desc": src["desc"], "mode": src["mode"]}
        print("OK   %-18s tries=%d count=%-7s sec=%-6s -> %s"
              % (key, entry["tries"], entry["count"],
                 entry["elapsed"], path), flush=True)

    os.makedirs("data", exist_ok=True)
    with open("data/status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in status["sources"].values() if v.get("ok"))
    print("")
    print("完成：成功/跳過 %d / 共 %d" % (ok, len(SOURCES)))
    print("失敗：%s" % (latest["failed"] or "無"))
    print("跳過：%s" % (latest["skipped"] or "無"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
