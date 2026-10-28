#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市場綜合損益表彙總（GitHub Actions 中繼用，2026/10/28 建）。
- 來源：MOPS 舊站 POST ajax_t163sb04（綜合損益表彙總表），上市 sii／上櫃 otc，去年 Q3／Q4 與今年 Q1～Q3（累計數；Q4＝全年）。
- 刻意抓全市場，避免公開 repo 洩漏觀察名單。
- 依表頭欄名取值（各產業別表格欄位不同）：營業收入、營業毛利、營業利益、稅前、本期淨利、基本每股盈餘。
- 寫入：data/derived/is_<期>.json（{代號: {...}}，累計數）與 data/derived/_t163_status.json。
- 紀律：單頁失敗不影響其他頁；不自動重試；每次請求間隔 3 秒（MOPS 連續請求會被重置連線）。
"""
import json, os, re, time, datetime, urllib.request, urllib.parse

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"
WANT = {
    "rev": ["營業收入", "收入", "收益"],
    "gp": ["營業毛利（毛損）淨額", "營業毛利（毛損）"],
    "oi": ["營業利益（損失）"],
    "pbt": ["稅前淨利（淨損）", "繼續營業單位稅前淨利（淨損）", "繼續營業單位稅前損益"],
    "ni": ["本期淨利（淨損）", "本期稅後淨利（淨損）"],
    "eps": ["基本每股盈餘（元）"],
}

def clean(s):
    return re.sub(r"<[^>]+>|&nbsp;|\s", "", s)

def num(s):
    s = clean(s).replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None

def post(typek, year, season):
    body = urllib.parse.urlencode({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                                   "isQuery": "Y", "TYPEK": typek, "year": str(year), "season": f"{season:02d}"}).encode()
    req = urllib.request.Request(URL, data=body, headers={"User-Agent": "Mozilla/5.0",
                                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.status, r.read().decode("utf-8", "replace")

def parse(html):
    out = {}
    for tb in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S | re.I):
        heads = [clean(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", tb, re.S | re.I)]
        if "公司代號" not in heads:
            continue
        idx = {}
        for k, names in WANT.items():
            for n in names:
                if n in heads:
                    idx[k] = heads.index(n); break
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S | re.I):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
            if len(tds) < len(heads) - 1 or not tds:
                continue
            code = clean(tds[0])
            if not re.fullmatch(r"\d{4}", code):
                continue
            row = {"name": clean(tds[1])}
            for k, i in idx.items():
                row[k] = num(tds[i]) if i < len(tds) else None
            out[code] = row
    return out

status = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pages": []}
os.makedirs("data/derived", exist_ok=True)
# 期別（2026/10/28 改為動態）：去年 Q3、Q4（Q4＝全年累計）＋今年 Q1～Q3；尚未公告者 0 列、不寫檔
Y = datetime.date.today().year - 1911
for (yy, season) in ((Y - 1, 3), (Y - 1, 4), (Y, 1), (Y, 2), (Y, 3)):
    per = f"{yy}Q{season}"
    merged = {}
    for typek in ("sii", "otc"):
        rec = {"period": per, "typek": typek, "http": None, "rows": 0, "err": None}
        try:
            st, html = post(typek, yy, season)
            rec["http"] = st
            rows = parse(html)
            rec["rows"] = len(rows)
            for c, r in rows.items():
                r["market"] = "listed" if typek == "sii" else "otc"
            merged.update(rows)
        except Exception as e:
            rec["err"] = f"{type(e).__name__}: {e}"[:200]
        status["pages"].append(rec)
        time.sleep(3)
    # 兩頁皆無錯誤才覆寫（避免單頁失敗時以半份資料蓋掉舊檔）
    if merged and not any(p["err"] for p in status["pages"] if p["period"] == per):
        json.dump(merged, open(f"data/derived/is_{per}.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(status, open("data/derived/_t163_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(status["pages"], ensure_ascii=False))
