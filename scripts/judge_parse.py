#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 財報燈號週報 · 確定性指標抽取器
# 讀中繼 data/mops/<期>/<代號>_<報表>.html（15 檔×3 表），抽出指標，輸出 JSON。
# 判燈號在下游做；本檔只負責「把數字抽對」，不做任何判斷。
#
# 2026/10/28 改版：
#  - 期別不再寫死：預設讀 data/mops/_last_run.json 的 periods_seen 取最新一期；
#    可用命令列參數覆寫（python judge_parse.py 115Q2）。
#  - 個股若最新期檔案尚未出現（404），自動退回上一期，並在該檔標 period 與 period_fallback。
#  - 「前季」改讀上一期檔案的「當季」欄（Q3 時累計−當季＝上半年合計，不等於 Q2，舊算法會錯）；
#    僅在 Q2 且上一期檔案不存在時，才以「累計−當季」推導 Q1（此時兩者相等）。
#  - 累計欄鍵名由 _H1 改為 _累計（Q3 起累計為前三季）。
#  - Q4（年報）只有全年欄、無當季欄，結構不同，本版不支援，遇到即列入 bad_files。
#  - 持股 15 檔：移除已出清 3044，新增 3231 緯創、3105 穩懋、8227 巨有。
import urllib.request, urllib.error, re, json, sys

BASE = "https://raw.githubusercontent.com/987989-droid/tw-stock-relay/main/data/mops/"
STOCKS = ["3363","6147","1519","1513","6239","6196","2449","6451","3035","2474","4958","6643",
          "3231","3105","8227"]
# 代號→公司名（防「靜默給錯公司」：每檔 HTML 必須含對應名，否則作廢）
NAME = {"3363":"上詮","6147":"頎邦","1519":"華城","1513":"中興電","6239":"力成",
        "6196":"帆宣","2449":"京元","6451":"訊芯","3035":"智原","2474":"可成",
        "4958":"臻鼎","6643":"M31","3231":"緯創","3105":"穩懋","8227":"巨有"}

def pkey(p):                      # "115Q2" -> (115, 2)
    y, q = p.split("Q"); return (int(y), int(q))
def prev_period(p):
    y, q = pkey(p)
    return f"{y-1}Q4" if q == 1 else f"{y}Q{q-1}"

def latest_period():
    try:
        lr = json.load(urllib.request.urlopen(urllib.request.Request(
            BASE + "_last_run.json", headers={"User-Agent": "p"}), timeout=45))
        ps = [p for p in (lr.get("periods_seen") or {}) if re.fullmatch(r"\d+Q[1-4]", p)]
        if ps: return max(ps, key=pkey), None
        return "115Q2", "_last_run.json 無 periods_seen，退用 115Q2"
    except Exception as e:
        return "115Q2", f"_last_run.json 讀取失敗（{e!r}），退用 115Q2"

if len(sys.argv) > 1:
    PERIOD, PERIOD_NOTE = sys.argv[1], "命令列指定"
else:
    PERIOD, PERIOD_NOTE = latest_period()

def fetch(stock, rpt, period):
    u = f"{BASE}{period}/{stock}_{rpt}.html"
    h = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"p"}), timeout=45).read().decode("utf-8","replace")
    t = re.sub(r"<[^>]+>", " ", h)
    t = re.sub(r"\s+", " ", t)
    return t

TOK = re.compile(r'\(?-?[\d,]+(?:\.\d+)?\)?')
def is_pct(tok):        # 百分比欄：±最多3位整數 + 剛好2位小數（如 100.00 / 21.76 / -21.43）
    core = tok.strip('()')
    return bool(re.fullmatch(r'-?\d{1,3}\.\d{2}', core))
def to_amt(tok):        # 金額：整數仟元，可含逗號、可負（-號或括號）；排除百分比
    if is_pct(tok): return None
    core = tok.strip('()')
    if not re.fullmatch(r'-?[\d,]+(?:\.\d+)?', core): return None
    val = float(core.replace(",",""))
    if tok.startswith('(') and tok.endswith(')'): val = -val
    return val

def amounts_after(text, labels, n=4):
    """回傳 label 後面前 n 個『金額』（跳過百分比欄）。labels 依序試，取第一個命中。"""
    for L in labels:
        i = text.find(L)
        if i < 0: continue
        seg = text[i+len(L): i+len(L)+260]
        out = []
        for m in TOK.finditer(seg):
            a = to_amt(m.group())
            if a is None: continue
            out.append(a)
            if len(out) >= n: break
        if out: return out
    return None

def eps_after(text):
    i = text.find("基本每股盈餘")
    if i < 0: return None
    seg = text[i+6: i+6+120]
    out = [float(m.group().strip('()').replace(",","")) * (-1 if m.group().startswith('(') else 1)
           for m in re.finditer(r'\(?-?\d{1,3}\.\d{2}\)?', seg)]
    return out[0] if out else None

def rate(a, b):
    try: return round(a/b*100, 2) if b not in (0, None) and a is not None else None
    except: return None

def extract(inc, cf, bs):
    rev = amounts_after(inc, ["營業收入合計","營業收入 "])
    cos = amounts_after(inc, ["營業成本合計","營業成本 "])
    gp  = amounts_after(inc, ["營業毛利（毛損）淨額","營業毛利（毛損）"])
    oi  = amounts_after(inc, ["營業利益（損失）"])
    pbt = amounts_after(inc, ["繼續營業單位稅前淨利（淨損）","稅前淨利（淨損）"])
    ni  = amounts_after(inc, ["本期淨利（淨損）","本期淨利"])
    ocf = amounts_after(cf, ["營業活動之淨現金流入（流出）","營業活動之淨現金流入","營業活動之淨現金流出"], 2) if cf else None
    ar  = amounts_after(bs, ["應收帳款淨額","應收帳款"], 2) if bs else None
    inv = amounts_after(bs, ["存貨"], 2) if bs else None
    return dict(rev=rev, cos=cos, gp=gp, oi=oi, pbt=pbt, ni=ni, ocf=ocf, ar=ar, inv=inv, eps=eps_after(inc))

def q(x, i=0):   # 綜合損益表每列 = [當季本年, 當季去年, 累計本年, 累計去年]
    return x[i] if x and len(x) > i else None

result = {"period": PERIOD, "period_note": PERIOD_NOTE, "stocks": {}, "bad_files": []}
if pkey(PERIOD)[1] == 4:
    result["bad_files"].append(f"期別 {PERIOD} 為年報（只有全年欄、無當季欄），本版 parser 不支援，全部未判")
    print(json.dumps(result, ensure_ascii=False, indent=1)); sys.exit(0)

for s in STOCKS:
    nm = NAME[s]; per = PERIOD; fallback = False
    try:
        try:
            inc = fetch(s,"t164sb04",per)
        except urllib.error.HTTPError as e:
            if e.code != 404: raise
            per = prev_period(PERIOD); fallback = True      # 最新期尚未出現 → 退回上一期
            inc = fetch(s,"t164sb04",per)
        cf = fetch(s,"t164sb05",per); bs = fetch(s,"t164sb03",per)
    except Exception as e:
        result["bad_files"].append(f"{s}: fetch {per} {e!r}"); continue
    if nm not in inc or nm not in cf or nm not in bs:
        result["bad_files"].append(f"{s}: 公司名『{nm}』未出現，作廢"); continue
    x = extract(inc, cf, bs)
    season = pkey(per)[1]
    rev_q, rev_qy = q(x["rev"],0), q(x["rev"],1)
    oi_q, pbt_q = q(x["oi"],0), q(x["pbt"],0)
    nop_q = (pbt_q - oi_q) if (pbt_q is not None and oi_q is not None) else None  # 業外淨額＝稅前−營業利益

    # 前季：優先讀上一期檔案的「當季」欄；Q2 且上一期無檔時，以 累計−當季 推導 Q1（兩者相等）
    oi_prev = ni_prev = None; prev_src = None; pp = prev_period(per)
    try:
        pinc = fetch(s,"t164sb04",pp)
        if nm in pinc:
            px = extract(pinc, None, None)
            oi_prev, ni_prev, prev_src = q(px["oi"],0), q(px["ni"],0), f"{pp} 當季欄"
    except Exception:
        pass
    if prev_src is None and season == 2:
        if q(x["oi"],2) is not None and oi_q is not None: oi_prev = q(x["oi"],2) - oi_q
        if q(x["ni"],2) is not None and q(x["ni"],0) is not None: ni_prev = q(x["ni"],2) - q(x["ni"],0)
        prev_src = "累計−當季（僅Q2成立）"

    ar_e, inv_e, cos_q = q(x["ar"],0), q(x["inv"],0), q(x["cos"],0)
    d = {
      "name": nm, "period": per, "period_fallback": fallback,
      "營收_當季": rev_q,
      "營收YoY_當季": rate(rev_q-rev_qy, rev_qy) if rev_q is not None and rev_qy else None,
      "毛利率_當季": rate(q(x["gp"],0), rev_q),
      "營業利益_當季": oi_q,
      "營業利益_累計": q(x["oi"],2),
      "業外_當季": nop_q,
      "稅前_當季": pbt_q, "稅前_累計": q(x["pbt"],2),
      "稅後_當季": q(x["ni"],0),  "稅後_累計": q(x["ni"],2),
      "業外佔稅前_當季": rate(nop_q, pbt_q),
      "EPS_當季": x["eps"],
      "營現_累計": q(x["ocf"],0),
      "營現對稅後_累計": rate(q(x["ocf"],0), q(x["ni"],2)),
      "應收_期末": ar_e, "存貨_期末": inv_e, "營業成本_當季": cos_q,
      "DSO天_當季": round(ar_e*91/rev_q,1) if ar_e is not None and rev_q else None,
      "存貨天_當季": round(inv_e*91/cos_q,1) if inv_e is not None and cos_q else None,
      "營業利益_前季": oi_prev, "稅後_前季": ni_prev, "前季來源": prev_src,
    }
    result["stocks"][s] = d

print(json.dumps(result, ensure_ascii=False, indent=1))
