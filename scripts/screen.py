#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
營收加速 × 股價落後 篩選＋地雷關（2026/10/28 建；排程與對話共用）。
- 名單不放 repo：由呼叫端以檔案傳入（任意文字，抓 4 碼代號）。本檔只含方法，不含任何名單。
- 用法：python3 scripts/screen.py <repo 根目錄> <名單檔> [--json] [--quarterly]
- 新鮮度檢查（排程用）：營收最新完整月須為上個月、beta 與 revhist 須於 3 日內產生；
  --quarterly 另要求損益最新完整期為應公告季（4月→去年Q4、5月→Q1、8月→Q2、11月→Q3）且 t163 於 3 日內產生。
  不新鮮 → 首行印「⚠️ 資料未更新」與原因，結束碼 2（呼叫端據此停住）。
- 讀：data/derived/revenue_hist.json、beta_alpha.json、is_<期>.json；data/monthly/pledge_*；
      data/daily/material_*、insider_*（近 30 日）；data/latest/quotes_*。
- 篩選：最近 3 個完整月（≥1500 家）營收 YoY 對前 3 個月
    候選＝YoY>0、加速>0、近 3 月相對大盤<0；
    嚴格＝YoY≥20%、加速≥10pp、相對大盤≤−10%、β≥1.0
- 燈號（機械規則，非買賣評級）：
    ⚫ 整體董監質押 ≥30%
    🟡 KY／任一董監個人質押 ≥20%／近 30 日重訊命中籌資・人事・裁罰・澄清・併購關鍵字／
       近 30 日內部人申報轉讓（贈與、信託除外）／最新季業外佔稅前 ≥50%／最新季營業利益 <0／
       日成交值 <1 億
    🟢 以上皆無
"""
import json, glob, os, re, sys, datetime

R, WL = sys.argv[1], sys.argv[2]
AS_JSON = "--json" in sys.argv
QUARTERLY = "--quarterly" in sys.argv
J = lambda p: json.load(open(os.path.join(R, p), encoding="utf-8"))
wl = list(dict.fromkeys(re.findall(r"(?<!\d)\d{4}(?!\d)", open(WL, encoding="utf-8").read())))

rev = J("data/derived/revenue_hist.json")
beta = {r["code"]: r for r in J("data/derived/beta_alpha.json")["rows"]}
beta_gen = J("data/derived/beta_alpha.json").get("generated_at_utc")
allm = sorted({m for v in rev.values() for m in v["months"]})
cnt = {m: sum(1 for v in rev.values() if m in v["months"]) for m in allm}
full = [m for m in allm if cnt[m] >= 1500]
q3, q2 = full[-3:], full[-6:-3]

def qyoy(c, ms):
    mm = rev.get(c, {}).get("months", {})
    if not all(m in mm and mm[m]["rev"] is not None and mm[m]["rev_ly"] for m in ms):
        return None
    return (sum(mm[m]["rev"] for m in ms) / sum(mm[m]["rev_ly"] for m in ms) - 1) * 100

rows, nodata = [], []
for c in wl:
    a, b = qyoy(c, q3), qyoy(c, q2)
    bt = beta.get(c)
    if a is None or b is None or not bt:
        nodata.append(c); continue
    rows.append(dict(code=c, name=rev[c]["name"], yoy=a, yoy_prev=b, acc=a - b, beta=bt["beta"],
                     rel3m=bt["rel_3m"] * 100, close=bt["last_close"], date=bt["last_date"]))
cand = [r for r in rows if r["yoy"] > 0 and r["acc"] > 0 and r["rel3m"] < 0]
strict = sorted([r for r in cand if r["yoy"] >= 20 and r["acc"] >= 10 and r["rel3m"] <= -10 and r["beta"] >= 1.0],
                key=lambda r: -r["acc"])

# ---- 地雷關資料 ----
def latest(d):
    fs = sorted(glob.glob(os.path.join(R, d, "*.json")))
    return fs[-1] if fs else None
pl = {}
for mk in ("listed", "otc"):
    f = latest(f"data/monthly/pledge_{mk}")
    if not f: continue
    ym = os.path.basename(f)[:-5]
    for x in json.load(open(f, encoding="utf-8")):
        hold = float(str(x.get("目前持股") or 0).replace(",", "") or 0)
        pg = float(str(x.get("設質股數") or 0).replace(",", "") or 0)
        pl.setdefault(x["公司代號"].strip(), {"ym": ym, "p": {}})["p"][x["姓名"]] = (hold, pg)

def pledge(c):
    d = pl.get(c)
    if not d: return None
    H = sum(h for h, _ in d["p"].values()); P = sum(p for _, p in d["p"].values())
    hi = sorted([(n, round(p / h * 100, 1)) for n, (h, p) in d["p"].items() if h and p / h >= 0.2], key=lambda t: -t[1])
    return {"ym": d["ym"], "overall": round(P / H * 100, 2) if H else 0.0, "high": hi[:3]}

cut = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
mat, ins = {}, {}
for mk in ("listed", "otc"):
    for f in sorted(glob.glob(os.path.join(R, f"data/daily/material_{mk}/*.json"))):
        if os.path.basename(f) < cut: continue
        for x in json.load(open(f, encoding="utf-8")):
            c = str(x.get("公司代號") or x.get("SecuritiesCompanyCode") or "").strip()
            s = re.sub(r"\s+", "", x.get("主旨 ") or x.get("主旨") or "")
            mat.setdefault(c, {})[s[:70]] = x.get("發言日期")
    for f in sorted(glob.glob(os.path.join(R, f"data/daily/insider_{mk}/*.json"))):
        if os.path.basename(f) < cut: continue
        for x in json.load(open(f, encoding="utf-8")):
            c = str(x.get("公司代號") or x.get("SecuritiesCompanyCode") or "").strip()
            ins.setdefault(c, set()).add((x.get("姓名"), (x.get("預定轉讓方式及股數-轉讓方式") or "").strip(),
                                          (x.get("預定轉讓總股數-自有持股") or "").strip()))

liq = {}
for x in J("data/latest/quotes_listed.json"):
    try: liq[x["Code"].strip()] = (float(x["TradeValue"]) / 1e8, x["Date"])
    except (ValueError, KeyError, AttributeError): pass
for x in J("data/latest/quotes_otc.json"):
    try: liq[x["SecuritiesCompanyCode"].strip()] = (float(x["TransactionAmount"]) / 1e8, x["Date"])
    except (ValueError, KeyError, AttributeError): pass

# 損益：取最新「≥1500 家」的期別與其前一期，換算單季
IS = {}
for f in glob.glob(os.path.join(R, "data/derived/is_*.json")):
    IS[os.path.basename(f)[3:-5]] = json.load(open(f, encoding="utf-8"))
def prev_per(p):
    y, s = int(p[:-2]), int(p[-1])
    return f"{y - 1}Q4" if s == 1 else f"{y}Q{s - 1}"
def single(c, p):
    cur = IS.get(p, {}).get(c)
    if not cur: return None
    if p.endswith("Q1"): return cur
    pr = IS.get(prev_per(p), {}).get(c)
    if not pr: return None
    return {k: (cur.get(k) - pr.get(k)) if cur.get(k) is not None and pr.get(k) is not None else None
            for k in ("rev", "gp", "oi", "pbt")}
fullp = sorted([p for p, d in IS.items() if len(d) >= 1500], key=lambda p: (int(p[:-2]), int(p[-1])))
LP = fullp[-1] if fullp else None
PP = prev_per(LP) if LP else None
def margins(c):
    out = {}
    for tag, p in (("prev", PP), ("last", LP)):
        s = single(c, p) if p else None
        if not s or not s.get("rev"): out[tag] = None; continue
        out[tag] = {"gm": s["gp"] / s["rev"] * 100 if s.get("gp") is not None else None,
                    "om": s["oi"] / s["rev"] * 100 if s.get("oi") is not None else None,
                    "oi": s.get("oi"), "pbt": s.get("pbt"),
                    "nonop": (s["pbt"] - s["oi"]) / s["pbt"] * 100 if s.get("pbt") and s.get("oi") is not None else None}
    return out

KW = r"辭任|解任|財務主管|會計主管|稽核主管|發言人|會計師|罰鍰|裁處|違反|澄清|轉換公司債|現金增資|私募|海外存託|GDR|減資|收購|併購|取得.*股權|100%股|重編|保留意見|違約|停工|停止交易|背書保證|資金貸與"
for r in strict:
    c = r["code"]
    r["pledge"] = pledge(c)
    r["material"] = mat.get(c, {})
    r["insider"] = sorted(ins.get(c, set()))
    r["liq"] = liq.get(c)
    r["ky"] = "KY" in r["name"]
    r["m"] = margins(c)
    why = []
    p = r["pledge"]
    if p and p["overall"] >= 30: why.append(("⚫", f"整體質押{p['overall']:.1f}%"))
    if r["ky"]: why.append(("🟡", "KY"))
    if p and p["high"]: why.append(("🟡", "個人質押" + "、".join(f"{n}{v}%" for n, v in p["high"])))
    hits = [f"{d} {s}" for s, d in r["material"].items() if re.search(KW, s)]
    if hits: why.append(("🟡", "重訊：" + "；".join(hits[:3])))
    tr = [t for t in r["insider"] if not re.search("贈與|信託", t[1] or "")]
    if tr: why.append(("🟡", "申報轉讓：" + "；".join(f"{n} {w} {s}股" for n, w, s in tr[:3])))
    last = (r["m"] or {}).get("last")
    if last and last["nonop"] is not None and last["nonop"] >= 50: why.append(("🟡", f"{LP}單季業外佔稅前{last['nonop']:.0f}%"))
    if last and last["oi"] is not None and last["oi"] < 0: why.append(("🟡", f"{LP}單季本業虧損"))
    if r["liq"] and r["liq"][0] < 1: why.append(("🟡", f"日成交值{r['liq'][0]:.2f}億"))
    r["flag"] = "⚫" if any(f == "⚫" for f, _ in why) else ("🟡" if why else "🟢")
    r["why"] = [w for _, w in why]

meta = dict(months_last=q3, months_prev=q2, wl=len(wl), nodata=nodata, cand=len(cand), strict=len(strict),
            beta_generated_utc=beta_gen, is_last=LP, is_prev=PP,
            pledge_ym={mk: (os.path.basename(latest(f"data/monthly/pledge_{mk}") or "")[:-5]) for mk in ("listed", "otc")})
# ---- 新鮮度 ----
today = datetime.date.today()
def age_days(iso):
    try: return (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(iso)).days
    except Exception: return 999
stale = []
py, pm = (today.year - 1911, today.month - 1) if today.month > 1 else (today.year - 1912, 12)
if not q3 or q3[-1] != f"{py}{pm:02d}": stale.append(f"營收最新完整月 {q3[-1] if q3 else '無'}，應為 {py}{pm:02d}")
for nm, iso in (("beta", beta_gen), ("revhist", J("data/derived/_revhist_status.json").get("run_at_utc"))):
    if age_days(iso) > 3: stale.append(f"{nm} 產生於 {iso}")
if QUARTERLY:
    Y = today.year - 1911
    want = {4: f"{Y-1}Q4", 5: f"{Y}Q1", 8: f"{Y}Q2", 11: f"{Y}Q3"}.get(today.month)
    if want and LP != want: stale.append(f"損益最新完整期 {LP}，應為 {want}")
    t163_iso = J("data/derived/_t163_status.json").get("run_at_utc") if os.path.exists(os.path.join(R, "data/derived/_t163_status.json")) else None
    if age_days(t163_iso) > 3: stale.append(f"t163 產生於 {t163_iso}")
meta["stale"] = stale
if stale and not AS_JSON:
    print("⚠️ 資料未更新：" + "；".join(stale)); sys.exit(2)
if AS_JSON:
    print(json.dumps({"meta": meta, "strict": strict}, ensure_ascii=False, indent=1, default=list)); sys.exit()

f1 = lambda v: "—" if v is None else f"{v:.1f}%"
L = [f"營收加速×股價落後 篩選｜營收 {q3[0]}–{q3[-1]} 對 {q2[0]}–{q2[-1]}｜β/股價 {strict[0]['date'] if strict else '—'}",
     f"名單 {len(wl)} 檔（缺資料 {len(nodata)}）→ 候選 {len(cand)} → 嚴格 {len(strict)}"]
order = {"⚫": 0, "🟡": 1, "🟢": 2}
for r in sorted(strict, key=lambda r: (order[r["flag"]], -r["acc"])):
    L.append("")
    L.append(f"{r['flag']} {r['code']} {r['name']}")
    L.append(f"營收YoY {r['yoy_prev']:.1f}%→{r['yoy']:.1f}%｜落後大盤 {r['rel3m']:.1f}%｜β {r['beta']:.2f}｜收 {r['close']}")
    m = r["m"] or {}
    if m.get("last"):
        pv = m.get("prev") or {}
        L.append(f"毛利率 {PP} {f1(pv.get('gm'))}→{LP} {f1(m['last']['gm'])}｜營益率 {f1(pv.get('om'))}→{f1(m['last']['om'])}")
    p = r["pledge"]
    L.append(f"整體質押 {p['overall']:.2f}%（{p['ym']}）" if p else "整體質押 查無")
    for w in r["why"]:
        if not w.startswith("整體質押"): L.append(w)
L.append("")
L.append("燈號為機械規則（質押／KY／重訊關鍵字／申報轉讓／業外／流動性），非買賣建議")
print("\n".join(L))
