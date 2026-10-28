#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市場月營收歷史（GitHub Actions 中繼用，2026/10/28 建；同日加入補抓模式）。
- 來源：MOPS 舊站月營收彙總靜態頁 mopsov.twse.com.tw/nas/t21/<sii|otc>/t21sc03_<民國年>_<月>_<0|1>.html
        （0＝國內公司、1＝外國／KY；編碼 MS950）。抓最近 15 個月 × 上市／上櫃 × 國內／外國。
- 刻意抓全市場，不抓追蹤清單，避免公開 repo 洩漏觀察名單。
- 解析：每列取 公司代號、名稱、當月營收、去年當月營收、MoM%、YoY%、累計 YoY%。
- 寫入：data/derived/revenue_hist.json（{代號: {name, market, months: {YYYMM: {...}}}}）
        與 data/derived/_revhist_status.json（逐頁 http／列數／錯誤）。
- 紀律：單頁失敗不影響其他頁；不自動重試；每頁間隔 1 秒。
"""
import json, os, re, time, datetime, urllib.request

BASE = "https://mopsov.twse.com.tw/nas/t21/{mk}/t21sc03_{y}_{m}_{t}.html"
now = datetime.date.today()
months = []
y, m = now.year - 1911, now.month - 1          # 從上個月往回
if m == 0:
    y, m = y - 1, 12
for _ in range(15):
    months.append((y, m))
    m -= 1
    if m == 0:
        y, m = y - 1, 12

def num(s):
    s = re.sub(r"<[^>]+>|&nbsp;|,|\s", "", s)
    try:
        return float(s)
    except ValueError:
        return None

out, status = {}, {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pages": []}
# 補抓模式：若已有前次結果，只重抓「錯誤或 0 列」的頁，其餘沿用（2026/10/28 首跑遭 MOPS 連線重置後加入）
todo = None
if os.path.exists("data/derived/_revhist_status.json") and os.path.exists("data/derived/revenue_hist.json"):
    prev = json.load(open("data/derived/_revhist_status.json", encoding="utf-8"))
    out = json.load(open("data/derived/revenue_hist.json", encoding="utf-8"))
    # 2026/10/28 修正：原只重抓「失敗頁」，新月份永遠不會進來。改為：最近 15 個月中「前次沒成功」的頁，
    # 加上最新 2 個月一律重抓（月營收 10 日截止，月初抓到的最新月可能不完整）。
    okprev = {(p["ym"], p["mk"], p["t"]) for p in prev["pages"] if not p["err"] and p["rows"]}
    allp = [(f"{a}{b:02d}", mk, t) for a, b in months for mk in ("sii", "otc") for t in (0, 1)]
    recent = {f"{a}{b:02d}" for a, b in months[:2]}
    todo = {k for k in allp if k not in okprev or k[0] in recent}
    status["pages"] = [p for p in prev["pages"] if (p["ym"], p["mk"], p["t"]) not in todo
                       and p["ym"] in {k[0] for k in allp}]
    status["mode"] = f"fill {len(todo)} pages"
SLEEP = 3 if todo is not None else 1
for (yy, mm) in months:
    ym = f"{yy}{mm:02d}"
    for mk in ("sii", "otc"):
        for t in (0, 1):
            if todo is not None and (ym, mk, t) not in todo:
                continue
            url = BASE.format(mk=mk, y=yy, m=mm, t=t)
            rec = {"ym": ym, "mk": mk, "t": t, "http": None, "rows": 0, "err": None}
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    rec["http"] = r.status
                    html = r.read().decode("cp950", "replace")
                for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                    tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
                    if len(tds) < 10:
                        continue
                    code = re.sub(r"<[^>]+>|&nbsp;|\s", "", tds[0])
                    if not re.fullmatch(r"\d{4}", code):
                        continue
                    name = re.sub(r"<[^>]+>|&nbsp;|\s", "", tds[1])
                    row = {"rev": num(tds[2]), "rev_ly": num(tds[4]), "mom": num(tds[5]),
                           "yoy": num(tds[6]), "cum": num(tds[7]), "cum_yoy": num(tds[9])}
                    d = out.setdefault(code, {"name": name, "market": "listed" if mk == "sii" else "otc",
                                              "foreign": t == 1, "months": {}})
                    d["months"][ym] = row
                    rec["rows"] += 1
            except Exception as e:
                rec["err"] = f"{type(e).__name__}: {e}"[:200]
            status["pages"].append(rec)
            time.sleep(SLEEP)

status["companies"] = len(out)
status["months"] = [f"{a}{b:02d}" for a, b in months]
os.makedirs("data/derived", exist_ok=True)
json.dump(out, open("data/derived/revenue_hist.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(status, open("data/derived/_revhist_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("companies", len(out), "pages ok", sum(1 for p in status["pages"] if p["rows"]), "/", len(status["pages"]))
