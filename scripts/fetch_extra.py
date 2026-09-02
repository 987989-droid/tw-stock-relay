#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_extra.py — 補抓 TWSE OpenAPI 上「地雷檢核」與「財報」類端點。

設計原則：
- 不動 scripts/fetch_daily.py，獨立執行、獨立失敗。
- 全市場公開資料，零過濾。本 repo 為公開 repo，
  不得寫入任何持股／追蹤清單資訊；過濾一律由讀取端自行處理。
- 自我限時：整步驟有總時間預算，用盡即停並照常寫出報告。
  （continue-on-error 只擋「步驟失敗」，擋不住「job 逾時」。）
- 端點順序＝重要性順序，預算用盡時犧牲的是後面的。

存檔模式：
- daily  → data/daily/<key>/<YYYY-MM-DD>.json
  裁罰、停止買賣、經營權異動這類是「狀態清單」不是當日事件，
  逐日留存快照，讀取端才能分辨「今天新上榜」與「早就在榜」，
  只對新增者告警，避免同一件事天天重複推播。
- period → data/quarterly/<key>/<年度>Q<季別>.json
  財報按實際報告期別存檔，可做季度比較。

實測註記（2026-09-02）：
- 已移除 t187ap09_L 與 t187ap10_L：兩者皆無「公司代號」欄位
  （前者 9 筆級距統計、後者僅月數計數），無法逐檔比對。
- 資產負債表僅彙總層級，無合約負債／應收帳款／存貨；
  TWSE OpenAPI 亦無現金流量表。該三項只能回 MOPS 財報附註。
"""
import json, os, time, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWSE = "https://openapi.twse.com.tw/v1"

TIMEOUT = 25
BUDGET = 300
MAX_BYTES = 40 * 1024 * 1024

SOURCES = [
    # ── 地雷檢核類（小檔、逐日快照）──
    ("control_suspend_listed",      "/opendata/t187ap26_L",    "經營權異動且營業範圍重大變更停止買賣", "daily"),
    ("control_altered_listed",      "/opendata/t187ap27_L",    "經營權異動且營業範圍重大變更列為變更交易", "daily"),
    ("penalty_listed",              "/opendata/t187ap22_L",    "上市公司金管會證券期貨局裁罰案件", "daily"),
    ("disclosure_violation_listed", "/opendata/t187ap23_L",    "上市公司違反資訊申報、重大訊息及說明記者會規定", "daily"),
    ("control_change_listed",       "/opendata/t187ap24_L",    "上市公司經營權異動", "daily"),
    ("shortfall_listed",            "/opendata/t187ap08_L",    "上市公司董監持股不足法定成數彙總表", "daily"),
    ("major_holder_listed",         "/opendata/t187ap02_L",    "上市公司持股逾10%大股東名單", "daily"),
    # ── 財報類（季頻，依報告期別存檔）──
    ("profitability_listed",        "/opendata/t187ap17_L",    "上市公司營益分析查詢彙總表", "period"),
    ("income_listed_ci",            "/opendata/t187ap06_L_ci", "上市公司綜合損益表(一般業)", "period"),
    ("balance_listed_ci",           "/opendata/t187ap07_L_ci", "上市公司資產負債表(一般業)", "period"),
]

# 實測無公司代號、無法逐檔比對，已停止抓取；一併從索引移除
DROP_KEYS = ["pledge_summary_listed", "shortfall_3m_listed"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tw-stock-relay"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        cl = r.headers.get("Content-Length")
        if cl and int(cl) > MAX_BYTES:
            raise ValueError("檔案過大 %s bytes，超過上限" % cl)
        raw = r.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("檔案過大，讀取超過上限 %d bytes" % MAX_BYTES)
        return r.status, raw


def out_path(key, mode, data, now):
    if mode == "daily":
        return "data/daily/%s/%s.json" % (key, now.strftime("%Y-%m-%d"))
    y = q = ""
    if data and isinstance(data[0], dict):
        y = str(data[0].get("年度") or "").strip()
        q = str(data[0].get("季別") or "").strip()
    tag = ("%sQ%s" % (y, q)) if y and q else "unknown-%s" % now.strftime("%Y%m")
    return "data/quarterly/%s/%s.json" % (key, tag)


def main():
    t_start = time.time()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    status = {"run_at_taipei": now.isoformat(), "budget_sec": BUDGET, "sources": {}}
    index_add = {}

    for key, path, desc, mode in SOURCES:
        elapsed = time.time() - t_start
        if elapsed > BUDGET:
            status["sources"][key] = {"ok": False, "skipped": True, "desc": desc,
                                      "err": "總時間預算 %ds 已用盡（已耗 %ds）" % (BUDGET, int(elapsed))}
            print(key, "SKIP 預算用盡")
            continue

        url = TWSE + path
        info = {"url": url, "desc": desc, "mode": mode}
        try:
            t0 = time.time()
            code, raw = fetch(url)
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError("回傳非 list")
            rel = out_path(key, mode, data, now)
            dst = os.path.join(ROOT, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            info.update({
                "ok": True, "status": code, "count": len(data), "bytes": len(raw),
                "elapsed": round(time.time() - t0, 2), "path": rel,
                "keys": list(data[0].keys()) if data and isinstance(data[0], dict) else [],
            })
            index_add[key] = {"path": rel, "count": len(data),
                              "desc": desc, "mode": mode}
        except urllib.error.HTTPError as e:
            info.update({"ok": False, "status": e.code, "err": "HTTPError %s" % e.code})
        except Exception as e:
            info.update({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        status["sources"][key] = info
        print(key, "OK" if info.get("ok") else "FAIL",
              info.get("count", info.get("err", "")))

    status["total_elapsed"] = round(time.time() - t_start, 1)
    with open(os.path.join(ROOT, "data", "extra_status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    mpath = os.path.join(ROOT, "data", "latest.json")
    try:
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)
        files = manifest.get("files") or {}
        for k in DROP_KEYS:
            files.pop(k, None)
        files.update(index_add)
        manifest["files"] = files
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("併入索引失敗（非致命）:", e)

    print("total_elapsed", status["total_elapsed"], "sec")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("fetch_extra failed (non-fatal): %r" % e)
