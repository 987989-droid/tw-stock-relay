#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_extra.py — 補抓 TWSE OpenAPI 上「地雷檢核」與「財報」類端點。

設計原則：
- 不動 scripts/fetch_daily.py，獨立執行、獨立失敗。
- 全市場公開資料，零過濾。本 repo 為公開 repo，
  不得寫入任何持股／追蹤清單資訊；過濾一律由讀取端自行處理。
- 任一端點失敗只記錄，不中斷其他端點、不讓工作流失敗。
- 每個端點的實際欄位 keys 會寫進 data/extra_status.json，
  供下游確認真實欄位名（例如「合約負債」實際叫什麼），不必猜。
"""
import json, os, time, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWSE = "https://openapi.twse.com.tw/v1"
TIMEOUT = 60

SOURCES = [
    # ── 地雷檢核類 ──
    ("pledge_summary_listed",       "/opendata/t187ap09_L",    "上市公司董監事質權設定占實際持有股數彙總表"),
    ("penalty_listed",              "/opendata/t187ap22_L",    "上市公司金管會證券期貨局裁罰案件"),
    ("disclosure_violation_listed", "/opendata/t187ap23_L",    "上市公司違反資訊申報、重大訊息及說明記者會規定"),
    ("shortfall_listed",            "/opendata/t187ap08_L",    "上市公司董監持股不足法定成數彙總表"),
    ("shortfall_3m_listed",         "/opendata/t187ap10_L",    "上市公司董監持股不足法定成數連續達3個月以上"),
    ("control_change_listed",       "/opendata/t187ap24_L",    "上市公司經營權異動"),
    ("control_suspend_listed",      "/opendata/t187ap26_L",    "經營權異動且營業範圍重大變更停止買賣"),
    ("control_altered_listed",      "/opendata/t187ap27_L",    "經營權異動且營業範圍重大變更列為變更交易"),
    ("major_holder_listed",         "/opendata/t187ap02_L",    "上市公司持股逾10%大股東名單"),
    # ── 財報類（季頻）──
    ("balance_listed_ci",           "/opendata/t187ap07_L_ci", "上市公司資產負債表(一般業)"),
    ("income_listed_ci",            "/opendata/t187ap06_L_ci", "上市公司綜合損益表(一般業)"),
    ("profitability_listed",        "/opendata/t187ap17_L",    "上市公司營益分析查詢彙總表"),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tw-stock-relay"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read()


def main():
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    status = {"run_at_taipei": now.isoformat(), "sources": {}}
    index_add = {}

    for key, path, desc in SOURCES:
        url = TWSE + path
        info = {"url": url, "desc": desc}
        try:
            t0 = time.time()
            code, raw = fetch(url)
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError("回傳非 list")
            rel = "data/latest/%s.json" % key
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
                              "desc": desc, "mode": "latest_only"}
        except urllib.error.HTTPError as e:
            info.update({"ok": False, "status": e.code, "err": "HTTPError %s" % e.code})
        except Exception as e:
            info.update({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        status["sources"][key] = info
        print(key, "OK" if info.get("ok") else "FAIL",
              info.get("count", info.get("err", "")))

    with open(os.path.join(ROOT, "data", "extra_status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    # 併入主索引，下游只要讀 data/latest.json 就找得到新資料源
    mpath = os.path.join(ROOT, "data", "latest.json")
    try:
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)
        files = manifest.get("files") or {}
        files.update(index_add)
        manifest["files"] = files
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("併入索引失敗（非致命）:", e)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("fetch_extra failed (non-fatal): %r" % e)
