"""大客戶資本支出（2026/11/11 建）。

來源：SEC EDGAR XBRL companyfacts（data.sec.gov，A 級：各公司 10-Q／10-K 申報數字）。
用途：AI 硬體供應鏈最上游的需求訊號——雲端大廠的現金資本支出（現金流量表「購置不動產廠房設備」）。
輸出：data/derived/hyperscaler_capex.json（不含任何持股資訊）。

注意：
- 現金流量表 Q2／Q3 為年初累計，單季值以「同起日累計相減」還原（method=derived）；
  10-K 的第四季＝全年 − 前三季累計。
- 各公司 concept 名稱不同，從候選清單中取「最近一期 end 最新」者。
- 甲骨文會計年度 6 月起，季末為 2／5／8／11 月，不併入日曆季合計。
- SEC 要求 User-Agent 含聯絡信箱格式，無則 403（2026/11/11 實測）。
"""
import json, time, urllib.request, datetime, sys, os
from datetime import date

UA = "tw-stock-relay research-bot@example.com"
COMPANIES = [  # ticker, CIK, 名稱
    ("GOOGL", 1652044, "Alphabet"),
    ("MSFT", 789019, "Microsoft"),
    ("AMZN", 1018724, "Amazon"),
    ("META", 1326801, "Meta"),
    ("ORCL", 1341439, "Oracle"),
]
CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    "PaymentsForProceedsFromProductiveAssets",
]
KEEP_Q = 12


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.loads(f.read())


def d(s):
    return date.fromisoformat(s)


def quarters(rows):
    # 同 (start,end) 取最晚申報
    by = {}
    for x in rows:
        if x.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
            continue
        k = (x["start"], x["end"])
        if k not in by or x["filed"] > by[k]["filed"]:
            by[k] = x
    out = {}
    for (s, e), x in by.items():
        days = (d(e) - d(s)).days
        if 80 <= days <= 100:
            out[e] = {"start": s, "end": e, "val": x["val"], "method": "direct", "filed": x["filed"], "form": x["form"]}
    for (s, e), x in by.items():
        if e in out:
            continue
        days = (d(e) - d(s)).days
        if days <= 100:
            continue
        prev = [(s2, e2) for (s2, e2) in by if s2 == s and 80 <= (d(e) - d(e2)).days <= 100]
        if not prev:
            continue
        p = by[prev[0]]
        out[e] = {"start": prev[0][1], "end": e, "val": x["val"] - p["val"], "method": "derived",
                  "filed": x["filed"], "form": x["form"], "basis": f"{s}~{e} 累計 − {s}~{prev[0][1]} 累計"}
    qs = sorted(out.values(), key=lambda q: q["end"])
    for q in qs:
        ly = [p for p in qs if 355 <= (d(q["end"]) - d(p["end"])).days <= 375]
        q["yoy_pct"] = round((q["val"] / ly[0]["val"] - 1) * 100, 1) if ly and ly[0]["val"] else None
        q["val_musd"] = round(q["val"] / 1e6)
    return qs[-KEEP_Q:]


def main():
    res = {"generated_at_utc": datetime.datetime.utcnow().isoformat(timespec="minutes") + "Z",
           "source": "SEC EDGAR XBRL companyfacts（10-Q／10-K）", "unit": "百萬美元（val_musd）",
           "note": "現金資本支出（購置不動產廠房設備）。method=derived 為年初累計相減還原之單季值。甲骨文會計季末為 2／5／8／11 月，不併入日曆季合計。",
           "companies": {}, "errors": []}
    for t, cik, nm in COMPANIES:
        try:
            j = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            g = j["facts"].get("us-gaap", {})
            best = None
            for c in CONCEPTS:
                rows = g.get(c, {}).get("units", {}).get("USD", [])
                if not rows:
                    continue
                last = max(r["end"] for r in rows)
                if best is None or last > best[1]:
                    best = (c, last, rows)
            if not best:
                raise RuntimeError("無候選 concept")
            res["companies"][t] = {"name": nm, "entity": j.get("entityName"), "cik": cik, "concept": best[0],
                                   "quarters": quarters(best[2])}
        except Exception as e:
            res["errors"].append(f"{t}: {e}")
        time.sleep(0.5)
    # 日曆季合計（季末 03-31／06-30／09-30／12-31，四家齊全才算）
    cal = {}
    for t, c in res["companies"].items():
        if t == "ORCL":
            continue
        for q in c["quarters"]:
            if q["end"][5:] in ("03-31", "06-30", "09-30", "12-31"):
                cal.setdefault(q["end"], {})[t] = q["val_musd"]
    need = [t for t in res["companies"] if t != "ORCL"]
    tot = []
    for e in sorted(cal):
        if all(t in cal[e] for t in need):
            tot.append({"end": e, "sum_musd": sum(cal[e].values()), "by": cal[e]})
    for x in tot:
        ly = [p for p in tot if 355 <= (d(x["end"]) - d(p["end"])).days <= 375]
        x["yoy_pct"] = round((x["sum_musd"] / ly[0]["sum_musd"] - 1) * 100, 1) if ly else None
    res["calendar_total_ex_orcl"] = tot
    os.makedirs("data/derived", exist_ok=True)
    with open("data/derived/hyperscaler_capex.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "companies"}, ensure_ascii=False, indent=1))
    for t, c in res["companies"].items():
        print(t, c["concept"], [(q["end"], q["val_musd"], q["method"], q["yoy_pct"]) for q in c["quarters"][-5:]])
    if res["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
