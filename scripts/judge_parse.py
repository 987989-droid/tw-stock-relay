#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 財報燈號週報 · 確定性指標抽取器
# 讀中繼 data/mops/<期>/<代號>_<報表>.html（13 檔×4 表），抽出 12 項指標，輸出 JSON。
# 判燈號在下游做；本檔只負責「把數字抽對」，不做任何判斷。
import urllib.request, re, json, sys

BASE = "https://raw.githubusercontent.com/987989-droid/tw-stock-relay/main/data/mops/"
PERIOD = "115Q2"
STOCKS = ["3363","6147","1519","1513","6239","6196","2449","6451","3035","2474","3044","4958","6643"]
# 代號→公司名（防「靜默給錯公司」：每檔 HTML 必須含對應名，否則作廢）
NAME = {"3363":"上詮","6147":"頎邦","1519":"華城","1513":"中興電","6239":"力成",
        "6196":"帆宣","2449":"京元","6451":"訊芯","3035":"智原","2474":"可成",
        "3044":"健鼎","4958":"臻鼎","6643":"M31"}

def fetch(stock, rpt):
    u = f"{BASE}{PERIOD}/{stock}_{rpt}.html"
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

result = {"period": PERIOD, "stocks": {}, "bad_files": []}
for s in STOCKS:
    try:
        inc = fetch(s,"t164sb04"); cf = fetch(s,"t164sb05"); bs = fetch(s,"t164sb03")
    except Exception as e:
        result["bad_files"].append(f"{s}: fetch {e!r}"); continue
    # 公司名防呆
    nm = NAME[s]
    if nm not in inc or nm not in cf or nm not in bs:
        result["bad_files"].append(f"{s}: 公司名『{nm}』未出現，作廢"); continue
    # 綜合損益表：每列 = [當季本年, 當季去年, 累計本年, 累計去年]
    rev = amounts_after(inc, ["營業收入合計","營業收入 "])
    cos = amounts_after(inc, ["營業成本合計","營業成本 "])
    gp  = amounts_after(inc, ["營業毛利（毛損）淨額","營業毛利（毛損）"])
    oi  = amounts_after(inc, ["營業利益（損失）"])
    nop = amounts_after(inc, ["營業外收入及支出"])
    pbt = amounts_after(inc, ["繼續營業單位稅前淨利（淨損）","稅前淨利（淨損）"])
    ni  = amounts_after(inc, ["本期淨利（淨損）","本期淨利"])
    eps = eps_after(inc)
    ocf = amounts_after(cf, ["營業活動之淨現金流入（流出）","營業活動之淨現金流入","營業活動之淨現金流出"], 2)
    ar  = amounts_after(bs, ["應收帳款淨額","應收帳款"], 2)
    inv = amounts_after(bs, ["存貨"], 2)
    def q(x,i=0):  # 當季本年
        return x[i] if x and len(x)>i else None
    rev_q, rev_qy = q(rev,0), q(rev,1)   # [當季本年, 當季去年, 累計本年, 累計去年]
    oi_q, pbt_q = q(oi,0), q(pbt,0)
    nop_q = (pbt_q - oi_q) if (pbt_q is not None and oi_q is not None) else None  # 業外淨額＝稅前−營業利益（定義推導）
    d = {
      "name": nm,
      "營收_當季": rev_q,
      "營收YoY_當季": rate(rev_q-rev_qy, rev_qy) if rev_q is not None and rev_qy else None,
      "毛利率_當季": rate(q(gp,0), rev_q),
      "營業利益_當季": oi_q,
      "營業利益_累計": q(oi,2),
      "業外_當季": nop_q,
      "稅前_當季": pbt_q, "稅前_累計H1": q(pbt,2),
      "稅後_當季": q(ni,0),  "稅後_累計H1": q(ni,2),
      "業外佔稅前_當季": rate(nop_q, pbt_q),
      "EPS_當季": eps,
      "營現_H1": q(ocf,0),
      "營現對稅後_H1": rate(q(ocf,0), q(ni,2)),
      "應收_期末": q(ar,0), "存貨_期末": q(inv,0), "營業成本_當季": q(cos,0),
      "DSO天_當季": round(q(ar,0)*91/rev_q,1) if q(ar,0) is not None and rev_q else None,
      "存貨天_當季": round(q(inv,0)*91/q(cos,0),1) if q(inv,0) is not None and q(cos,0) else None,
      # 前季(Q1)=累計H1−當季Q2（§推導優先，視同一手）
      "營業利益_前季Q1": (q(oi,2)-q(oi,0)) if q(oi,2) is not None and q(oi,0) is not None else None,
      "稅後_前季Q1": (q(ni,2)-q(ni,0)) if q(ni,2) is not None and q(ni,0) is not None else None,
    }
    result["stocks"][s] = d

print(json.dumps(result, ensure_ascii=False, indent=1))
