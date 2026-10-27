#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOPS 四大財報抓取（GitHub Actions 中繼用）。
- 對象：15 檔持股 × 4 張合併報表（ajax_t164sb03/04/05/06）。
- 取期：isnew=true 取「最新一期」；期別與公司代號一律由回傳 HTML 內
        XBRL 連結的 CO_ID / SYEAR / SSEASON 抽出（四表 100% 都有此欄），
        不靠中文標頭（sb06 權益變動表沒有中文期別標頭）。
- 寫入：data/mops/<期>/<代號>_<表>.html，期別如 115Q2（民國年 = SYEAR-1911）。
- 防呆：回傳代號 ≠ 請求代號即整筆作廢（擋 MOPS 靜默給錯公司）；抽不到
        XBRL 標記（查無資料／錯誤頁）亦不落檔，只記錄失敗。
- 紀律：單檔失敗不影響其他檔；不自動重試；每檔之間節流 1 秒。
        每次執行寫 data/mops/_last_run.json（逐檔 http/bytes/期別/代號/ok/err）。
機制來源：GitHub Actions runner 直打 mopsov POST ajax_t164sb05 已於 2026/09/13
          實測 HTTP 200、數字正確（sandbox bash 對 mopsov 為 403，故本檔只在
          Actions 端跑；parser 的期別/代號抽取已以 repo 內 52 檔樣本離線實測）。
"""

import json
import os
import re
import time
import datetime
import urllib.request
import urllib.parse

STOCKS = ["1513", "1519", "2449", "2474", "3035", "3105", "3231", "3363",
          "4958", "6147", "6196", "6239", "6451", "6643", "8227"]

TABLES = {
    "t164sb03": "資產負債表",
    "t164sb04": "綜合損益表",
    "t164sb05": "現金流量表",
    "t164sb06": "權益變動表",
}

BASE = "https://mopsov.twse.com.tw/mops/web/ajax_"
UA = "Mozilla/5.0"
TIMEOUT = 60
SLEEP = 1.0

# 四表皆含此 XBRL 連結，為期別＋代號的通用可靠來源
XBRL_RE = re.compile(r"CO_ID=(\d+)&SYEAR=(\d+)&SSEASON=(\d+)")


def fetch(table, co_id):
    body = urllib.parse.urlencode({
        "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
        "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
        "isnew": "true", "co_id": co_id, "year": "", "season": "",
    }).encode()
    req = urllib.request.Request(
        BASE + table, data=body,
        headers={"User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", "replace")


def parse_meta(html):
    """由 HTML 抽出 {co_id, period, syear, sseason}；抽不到回 None。"""
    m = XBRL_RE.search(html)
    if not m:
        return None
    co, syear, sseason = m.group(1), int(m.group(2)), int(m.group(3))
    return {"co_id": co,
            "period": "%dQ%d" % (syear - 1911, sseason),
            "syear": syear, "sseason": sseason}


def main():
    run = {
        "fetched_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "requested_stocks": STOCKS,
        "tables": list(TABLES.keys()),
        "results": [],
        "ok_count": 0,
        "fail_count": 0,
        "periods_seen": {},
    }
    for co_id in STOCKS:
        for table in TABLES:
            rec = {"co_id": co_id, "table": table, "ok": False, "err": None,
                   "http": None, "bytes": 0,
                   "detected_co_id": None, "period": None}
            try:
                status, html = fetch(table, co_id)
                rec["http"] = status
                rec["bytes"] = len(html)
                meta = parse_meta(html)
                if meta is None:
                    rec["err"] = "無 XBRL 標記（查無資料或錯誤頁）"
                elif meta["co_id"] != co_id:
                    rec["detected_co_id"] = meta["co_id"]
                    rec["err"] = ("代號不符：請求 %s 回傳 %s（疑給錯公司，作廢）"
                                  % (co_id, meta["co_id"]))
                else:
                    rec["detected_co_id"] = meta["co_id"]
                    rec["period"] = meta["period"]
                    outdir = os.path.join("data", "mops", meta["period"])
                    os.makedirs(outdir, exist_ok=True)
                    path = os.path.join(outdir, "%s_%s.html" % (co_id, table))
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(html)
                    rec["ok"] = True
                    run["periods_seen"][meta["period"]] = \
                        run["periods_seen"].get(meta["period"], 0) + 1
            except Exception as e:
                rec["err"] = "%s: %s" % (type(e).__name__, e)

            run["results"].append(rec)
            run["ok_count" if rec["ok"] else "fail_count"] += 1
            print("%s %s http=%s bytes=%s period=%s ok=%s err=%s"
                  % (co_id, table, rec["http"], rec["bytes"],
                     rec["period"], rec["ok"], rec["err"]))
            time.sleep(SLEEP)

    os.makedirs("data/mops", exist_ok=True)
    with open("data/mops/_last_run.json", "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)
    print("DONE ok=%d fail=%d periods=%s"
          % (run["ok_count"], run["fail_count"], run["periods_seen"]))


if __name__ == "__main__":
    main()
