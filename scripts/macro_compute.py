"""宏觀專案季度計算：讀 macro_collect.py 與中繼既有資料，依「五層追蹤指標 v0.1」的公式與判讀規則算出數字與燈號。
輸入：data/selftest/macro/（us_facts.json、nvda_ar.json、fr_bis.json、hkex/*.txt、tw_wc.json）、
      data/selftest/segments.json、data/derived/revenue_hist.json、data/derived/is_<期>.json
輸出：data/selftest/macro/summary.json（全部數字）、summary.md（推播正文）。
任何一項抽不到即標 ⚠️ 並寫明原因，不以舊值或推估補。"""
import json, os, re, glob, datetime as dt

IN = "data/selftest/macro"
S = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "errors": []}


def err(where, e):
    S["errors"].append(f"{where}: {e}")


def days(r):
    return (dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(r["start"])).days


def quarterly(rows):
    """單季數：直接取約 3 個月者；年初至今累計則與同起點、早一季的累計相減。"""
    m = {}
    for r in rows:
        if not r.get("start"):
            continue
        k = (r["start"], r["end"])
        if k not in m or r["filed"] > m[k]["filed"]:
            m[k] = r
    rows = list(m.values())
    q = {}
    for r in rows:
        if 80 <= days(r) <= 100:
            q[r["end"]] = r["val"]
    for r in rows:
        if days(r) > 100:
            for p in rows:
                if p["start"] == r["start"] and p["end"] < r["end"] and \
                        80 <= (dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(p["end"])).days <= 100:
                    q.setdefault(r["end"], r["val"] - p["val"])
    return dict(sorted(q.items()))


def pct(a, b):
    return round((a / b - 1) * 100, 1) if b else None


def yago(end):
    d = dt.date.fromisoformat(end)
    return d.replace(year=d.year - 1)


def near(q, target, tol=10):
    """在 q 中找與 target 日期相差 tol 天內的鍵（各家季底日不同）。"""
    for k in q:
        if abs((dt.date.fromisoformat(k) - target).days) <= tol:
            return k
    return None


# ---------- 美國 ----------
try:
    US = json.load(open(f"{IN}/us_facts.json"))
    CAPTAG = {"MSFT": "PaymentsToAcquirePropertyPlantAndEquipment", "GOOGL": "PaymentsToAcquirePropertyPlantAndEquipment",
              "META": "PaymentsToAcquirePropertyPlantAndEquipment", "AMZN": "PaymentsToAcquireProductiveAssets",
              "NVDA": "PaymentsToAcquireProductiveAssets"}
    cap = {t: quarterly(US[t][CAPTAG[t]]) for t in CAPTAG}
    ocf = {t: quarterly(US[t]["NetCashProvidedByUsedInOperatingActivities"]) for t in CAPTAG}
    fin = {t: quarterly(US[t].get("RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability", [])) for t in CAPTAG}
    opl = {t: quarterly(US[t].get("RightOfUseAssetObtainedInExchangeForOperatingLeaseLiability", [])) for t in CAPTAG}
    BIG4 = ["MSFT", "GOOGL", "AMZN", "META"]
    # 以四家都有資料的季底（月底）為準
    ends = sorted(set.intersection(*[set(cap[t]) for t in BIG4]))
    ends = [e for e in ends if e.endswith(("03-31", "06-30", "09-30", "12-31"))]
    tot = {e: sum(cap[t][e] for t in BIG4) for e in ends}
    last, prev = ends[-1], ends[-2]
    ly = near(tot, yago(last))
    l1 = {"quarter_end": last, "total": tot[last], "prev": tot[prev], "qoq": pct(tot[last], tot[prev]),
          "yoy": pct(tot[last], tot[ly]) if ly else None, "by_co": {t: cap[t][last] for t in BIG4},
          "series": tot, "qoq_series": {e: pct(tot[e], tot[ends[i - 1]]) for i, e in enumerate(ends) if i}}
    qs = [l1["qoq_series"][e] for e in ends[-2:]]
    l1["light"] = "🔴" if all(x is not None and x < 0 for x in qs) else "🟢" if l1["qoq"] > 0 else "🟡"
    S["L1_us"] = l1

    # 5b：（capex＋新增融資租賃）÷ 營業現金流
    def r5b(e, with_op=False):
        num = sum(cap[t][e] + fin[t].get(e, 0) + (opl[t].get(e, 0) if with_op else 0) for t in BIG4)
        return round(num / sum(ocf[t][e] for t in BIG4), 3)
    b5 = {e: r5b(e) for e in ends[-4:]}
    vals = list(b5.values())
    S["L3_5b"] = {"main": b5, "capex_only": {e: round(tot[e] / sum(ocf[t][e] for t in BIG4), 3) for e in ends[-4:]},
                  "with_oplease": {e: r5b(e, True) for e in ends[-4:]},
                  "fcf_by_co": {t: ocf[t][last] - cap[t][last] for t in BIG4},
                  "light": "🔴" if vals[-1] > 1 and vals[-2] > 1 else "🟡" if vals[-1] > 1 else "🟢",
                  "note": "META 單季租賃未標記，未計入"}

    # NVIDIA 毛利率、營業現金流、DSO、存貨天數（5、5c）
    gp, rev = quarterly(US["NVDA"]["GrossProfit"]), quarterly(US["NVDA"]["Revenues"])
    ne = sorted(set(gp) & set(rev))
    n1, n0 = ne[-1], ne[-2]
    det = US.get("NVDA_ocf_detail", {})
    bal = lambda tag: {r["end"]: r["val"] for r in det.get(tag, [])}
    ar, inv = bal("AccountsReceivableNetCurrent"), bal("InventoryNet")
    dso = lambda e: round(ar[e] / rev[e] * 91, 1) if e in ar else None
    invd = lambda e: round(inv[e] / (rev[e] - gp[e]) * 91, 1) if e in inv else None
    nv = {"quarter_end": n1, "gm": round(gp[n1] / rev[n1] * 100, 2), "gm_prev": round(gp[n0] / rev[n0] * 100, 2),
          "rev_qoq": pct(rev[n1], rev[n0]), "ocf": ocf["NVDA"].get(n1), "ocf_prev": ocf["NVDA"].get(n0),
          "dso": [dso(e) for e in ne[-3:]], "inv_days": [invd(e) for e in ne[-3:]], "dso_ends": ne[-3:]}
    nv["gm_light"] = "🔴" if nv["rev_qoq"] > 0 and nv["gm"] < nv["gm_prev"] - 1 else "🟢"
    d3 = nv["dso"]
    ext = False
    try:
        ext = any("extended payment terms" in s for s in json.load(open(f"{IN}/nvda_ar.json"))["sentences"])
    except Exception as e:
        err("nvda_ar", e)
    nv["extended_terms_mentioned"] = ext
    up1 = d3[-1] is not None and d3[-2] is not None and d3[-1] > d3[-2]
    up2 = up1 and d3[-3] is not None and d3[-2] > d3[-3]
    nv["light_5c"] = "🔴" if up2 else "🟡" if (up1 and ext) or up1 else "🟢"
    S["L3_nvda"] = nv
except Exception as e:
    err("美國 companyfacts", e)

# 6：空方題
try:
    seg = json.load(open("data/selftest/segments.json"))
    SG = {}
    for tk, mem in (("AMZN", "amzn:AmazonWebServicesSegmentMember"), ("GOOGL", "goog:GoogleCloudMember")):
        for f in seg["companies"][tk]["filings"]:
            for r in f.get("facts", []):
                if r["member"] == mem and r["concept"].endswith("RevenueFromContractWithCustomerExcludingAssessedTax"):
                    SG[(tk, r["end"])] = r["val"]
    out6 = {}
    for e in sorted({e for (_, e) in SG}):
        y = str(yago(e))
        if all((t, x) in SG for t in ("AMZN", "GOOGL") for x in (e, y)) and all(x in cap[t] for t in ("AMZN", "GOOGL") for x in (e, y)):
            num = sum(SG[(t, e)] - SG[(t, y)] for t in ("AMZN", "GOOGL"))
            den = sum(cap[t][e] - cap[t][y] for t in ("AMZN", "GOOGL"))
            out6[e] = {"ratio": round(num / den, 3), "cloud_rev_yoy_inc": num, "capex_yoy_inc": den}
    k = sorted(out6)
    r = [out6[x]["ratio"] for x in k]
    light = "🔴" if len(r) >= 3 and r[-1] < r[-2] < r[-3] else "🟡" if len(r) >= 2 and r[-1] < r[-2] else "🟢"
    S["L3_6"] = {"series": out6, "light": light}
except Exception as e:
    err("空方題", e)

# ---------- 中國 ----------
def latest_two(name):
    fs = sorted(glob.glob(f"{IN}/hkex/{name}_*.txt"))
    return [open(f, encoding="utf-8").read() for f in fs[-2:]][::-1], fs[-2:][::-1]


CN = {}
try:
    txt, files = latest_two("tencent")
    ln = next(l for l in txt[0].splitlines() if re.match(r"\s*資本開支\s*\(d\)", l))
    v = [float(x.replace(",", "")) for x in re.findall(r"[\d,]{3,}", ln)]
    CN["騰訊"] = {"cur": v[0], "prev": v[1], "ly": v[2], "file": files[0]}
except Exception as e:
    err("騰訊", e)
try:
    txt, files = latest_two("baidu")
    ln = next(l for l in txt[0].splitlines() if "減：資本開支" in l)
    v = [float(x.replace(",", "")) for x in re.findall(r"\(([\d,]+)\)", ln)]
    CN["百度"] = {"cur": v[8], "prev": v[5], "ly": v[2], "file": files[0]}  # 三期×(不含愛奇藝, 愛奇藝, 合併)
except Exception as e:
    err("百度", e)
try:
    txt, files = latest_two("alibaba")
    flat = lambda t: re.sub(r"\s+", "", t)
    m = re.search(r"止季度，資本性支出為人民幣([\d.]+)億元.*?同期的人民幣([\d.]+)億元", flat(txt[0]))
    cur, ly = float(m.group(1)) * 100, float(m.group(2)) * 100
    p = re.search(r"止季度，資本性支出為人民幣([\d.]+)億元", flat(txt[1])) or \
        re.search(r"止三個月的投資活動.*?資本性支出人民幣([\d,]+)百萬元", flat(txt[1]))
    prev = float(p.group(1)) * 100 if "億" in p.group(0) else float(p.group(1).replace(",", ""))
    CN["阿里"] = {"cur": cur, "prev": prev, "ly": ly, "file": files[0]}
except Exception as e:
    err("阿里", e)
if len(CN) == 3:
    c, p, y = (sum(CN[k][x] for k in CN) for x in ("cur", "prev", "ly"))
    S["L1_cn"] = {"total": c, "qoq": pct(c, p), "yoy": pct(c, y), "by_co": CN,
                  "light": "🟢" if c > p else "🟡", "note": "百萬人民幣；結論強度低於美國一級"}
try:
    txt, files = latest_two("smic")
    lines = txt[0].splitlines()
    u = next(l for l in lines if "產能利用率(2)" in l)
    uv = [float(x) for x in re.findall(r"([\d.]+)%", u)]
    rv = next(l for l in lines if re.match(r"\s*收入\s+[\d,]+", l))
    r = [float(x.replace(",", "")) for x in re.findall(r"[\d,]{4,}", rv)]
    S["L4_smic"] = {"util": uv[0], "util_prev": uv[1], "rev_kusd": r[0], "rev_prev": r[1], "rev_qoq": pct(r[0], r[1]),
                    "file": files[0], "light": "🟢" if uv[0] > 90 and r[0] > r[1] else "🟡"}
except Exception as e:
    err("中芯", e)

# ---------- 台股 ----------
try:
    H = json.load(open("data/derived/revenue_hist.json"))
    months = sorted({m for v in H.values() for m in v.get("months", {})})
    full = [m for m in months if sum(1 for v in H.values() if m in v.get("months", {})) > 1500]
    qmonths = [m for m in full if m[-2:] in ("03", "06", "09", "12")]
    q_end = qmonths[-1]
    idx = full.index(q_end)
    Q = [full[idx - 2:idx + 1], full[idx - 5:idx - 2]]
    B = {"晶片封測": ["2330", "3711"], "記憶體": ["2408", "2344"], "組裝": ["2382", "3231", "2317"],
         "光通訊": ["3363", "4979"], "電力散熱": ["2308", "3017"]}

    def qy(codes, ms):
        c = sum(H[x]["months"][m]["rev"] for x in codes for m in ms)
        l = sum(H[x]["months"][m]["rev_ly"] for x in codes for m in ms)
        return pct(c, l)
    L2 = {k: {"cur": qy(v, Q[0]), "prev": qy(v, Q[1])} for k, v in B.items()}
    down = B["組裝"] + B["光通訊"] + B["電力散熱"]
    L2["下游合計"] = {"cur": qy(down, Q[0]), "prev": qy(down, Q[1])}
    share = sum(H["2330"]["months"][m]["rev"] for m in Q[0]) / sum(H[x]["months"][m]["rev"] for x in B["晶片封測"] + B["記憶體"] for m in Q[0])
    us_yoy = S.get("L1_us", {}).get("yoy")
    us_prev = None
    try:
        e2 = sorted(S["L1_us"]["series"])[-2]
        ly2 = near(S["L1_us"]["series"], yago(e2))
        us_prev = pct(S["L1_us"]["series"][e2], S["L1_us"]["series"][ly2])
    except Exception:
        pass
    gap_now = round(us_yoy - L2["下游合計"]["cur"], 1) if us_yoy is not None else None
    gap_prev = round(us_prev - L2["下游合計"]["prev"], 1) if us_prev is not None else None
    S["L2"] = {"months": Q[0], "prev_months": Q[1], "baskets": L2, "tsmc_share_upstream": round(share * 100, 1),
               "gap_downstream_vs_capex": [gap_prev, gap_now],
               "light": "🟡" if gap_now is not None and gap_prev is not None and gap_now > gap_prev else "🟢",
               "note": "美國 capex 年增率與台股月營收期別可能不同季，比較方向不比水位"}
    S["L5"] = {n: {"cur": qy([c], Q[0]), "prev": qy([c], Q[1])} for n, c in (("上詮CPO", "3363"), ("華星光CPO", "4979"), ("台達電HVDC", "2308"))}
except Exception as e:
    err("台股月營收", e)

try:
    isf = sorted(glob.glob("data/derived/is_*.json"))
    good = [f for f in isf if len(json.load(open(f))) > 1500]
    f1, f0 = good[-1], good[-2]
    A, P = json.load(open(f1)), json.load(open(f0))
    same_year = os.path.basename(f1)[3:6] == os.path.basename(f0)[3:6]

    def gm(codes):
        r1 = sum(A[c]["rev"] for c in codes); g1 = sum(A[c]["gp"] for c in codes)
        if same_year:
            r0 = sum(P[c]["rev"] for c in codes); g0 = sum(P[c]["gp"] for c in codes)
            return round((g1 - g0) / (r1 - r0) * 100, 2), None
        return round(g1 / r1 * 100, 2), None
    S["L3_tw_gm"] = {"period": os.path.basename(f1)[3:8], "upstream": gm(["2330", "3711", "2408", "2344"])[0],
                     "downstream": gm(["2382", "3231", "2317", "3363", "4979", "2308", "3017"])[0],
                     "note": "單季＝本期累計－前期累計；跨年度時為累計數"}
except Exception as e:
    err("台股毛利率", e)

try:
    WC = json.load(open(f"{IN}/tw_wc.json"))
    out = {}
    for co, per in WC.items():
        out[co] = {}
        for p, t in per.items():
            def row(tbl, key, col=1):
                for r in t[tbl]:
                    if r[0] == key:
                        return float(r[col].replace(",", ""))
                return 0.0
            rev = row("t164sb04", "營業收入合計")
            arv = row("t164sb03", "應收帳款淨額") + row("t164sb03", "應收帳款－關係人淨額")
            apv = row("t164sb03", "應付帳款") + row("t164sb03", "應付帳款－關係人")
            iv = row("t164sb03", "存貨")
            out[co][p] = {"ar_days": round(arv / rev * 91, 1), "ap_days": round(apv / rev * 91, 1), "inv_days": round(iv / rev * 91, 1)}
    out = {c: dict(sorted(v.items())) for c, v in out.items()}
    complete = [c for c in out if len(out[c]) >= 2]
    if len(complete) < 3:
        light = "⚪"
        err("台股組裝營運資金", f"僅 {complete} 有兩期資料，其餘抓取失敗（見 status.json tw_wc），不亮燈")
    else:
        ar = lambda i: sum(list(out[c].values())[i]["ar_days"] for c in complete)
        light = "🟡" if ar(-1) > ar(-2) else "🟢"
    S["L3_5d"] = {"by_co": out, "light": light, "note": "以單季營收為分母；三家應收天數合計單季拉長🟡、連兩季拉長🔴（需跨期資料）"}
except Exception as e:
    err("台股組裝營運資金", e)

# ---------- L4 BIS ----------
try:
    FR = json.load(open(f"{IN}/fr_bis.json"))["results"]
    qk = lambda d: f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"
    agg = {}
    for r in FR:
        k = qk(r["publication_date"])
        a = agg.setdefault(k, {"rule": 0, "notice": 0})
        a["rule" if r["type"] == "Rule" else "notice"] += 1
    # 規則全文分類（只依標題＋摘要＋全文關鍵字計數，機械規則，不讀政策意圖）
    EASE = re.compile(r"removing|removal|easing|case-by-case|favorable treatment|suspension|extending|streamlining", re.I)
    TIGHT = re.compile(r"adding \d+|additions to the entity list|restrict|new license requirement|imposes", re.I)
    rules = json.load(open(f"{IN}/fr_rules.json"))
    cls, watch = {}, []
    for r in rules:
        txt = f"{r.get('title') or ''} {r.get('abstract') or ''}"
        semi = sum((r.get("semi_terms") or {}).values())
        relevant = semi >= 3 or (r.get("china_mentions") or 0) >= 5
        d = "放寬" if EASE.search(txt) else "收緊" if TIGHT.search(txt) else "中性"
        cn_add = 0
        m = re.search(r"adding (\d+) entr(?:y|ies).*?China\)? \((\d+)\)", txt)
        if m:
            cn_add = int(m.group(2))
        q = qk(r["publication_date"])
        c = cls.setdefault(q, {"相關收緊": 0, "相關放寬": 0, "中國實體新增": 0, "items": []})
        if relevant:
            c["相關收緊" if d == "收緊" else "相關放寬" if d == "放寬" else "items"] += 0 if d == "中性" else 1
            c["items"].append(f"{r['publication_date']} {d} {r['title'][:60]}")
        c["中國實體新增"] += cn_add
        for mm in re.finditer(r"set to end ([A-Z][a-z]+ \d{1,2}, \d{4})", txt):
            try:
                end = dt.datetime.strptime(mm.group(1), "%B %d, %Y").date()
                if 0 <= (end - dt.date.today()).days <= 120:
                    watch.append(f"{end} 到期：{r['title'][:60]}")
            except ValueError:
                pass
    curq = f"{dt.date.today().year}Q{(dt.date.today().month - 1) // 3 + 1}"
    full = sorted(q for q in cls if q < curq)
    lq = full[-1] if full else None
    L = cls.get(lq, {})
    if not L:
        light = "⚪"
    elif L["相關收緊"] > L["相關放寬"] or L["中國實體新增"] > 0:
        light = "🔴"
    elif L["相關放寬"] > L["相關收緊"]:
        light = "🟢"
    else:
        light = "🟡"
    S["L4_bis"] = {"by_quarter": dict(sorted(agg.items())), "classified": dict(sorted(cls.items())), "last_full_quarter": lq,
                   "light": light, "watch": watch,
                   "note": "相關＝半導體／AI 關鍵字≥3 次或提及中國≥5 次；方向依標題與摘要關鍵字機械分類"}
except Exception as e:
    err("BIS", e)

# ---------- 輸出 ----------
json.dump(S, open(f"{IN}/summary.json", "w"), ensure_ascii=False, indent=1)
f = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
L = ["[晨報推送] 中美AI資金流向・季度更新", ""]
if "L1_us" in S:
    a = S["L1_us"]
    L.append(f"L1 美國四大capex {a['light']} {a['quarter_end']} {f(a['total']/1e6)}百萬美元 QoQ {a['qoq']}% YoY {a['yoy']}%")
if "L1_cn" in S:
    a = S["L1_cn"]
    L.append(f"L1 中國三大capex {a['light']} {f(a['total'])}百萬人民幣 QoQ {a['qoq']}% YoY {a['yoy']}%（強度低一級）")
if "L2" in S:
    a = S["L2"]; b = a["baskets"]
    L.append(f"L2 {a['light']} 下游 {b['下游合計']['prev']}→{b['下游合計']['cur']}% 落差 {a['gap_downstream_vs_capex'][0]}→{a['gap_downstream_vs_capex'][1]}pp")
    L.append("   " + "／".join(f"{k} {v['cur']}%（{v['prev']}）" for k, v in b.items() if k != "下游合計"))
if "L3_nvda" in S:
    a = S["L3_nvda"]
    L.append(f"L3 NVDA毛利 {a['gm_light']} {a['gm_prev']}→{a['gm']}%｜DSO {a['light_5c']} {a['dso']}天 延長付款{'有' if a['extended_terms_mentioned'] else '無'}")
if "L3_5b" in S:
    a = S["L3_5b"]
    L.append(f"L3 投入÷現金流 {a['light']} " + " → ".join(str(v) for v in a["main"].values()))
if "L3_6" in S:
    a = S["L3_6"]
    L.append(f"空方題 {a['light']} " + " → ".join(f"{v['ratio']}" for v in a["series"].values()))
if "L3_5d" in S:
    a = S["L3_5d"]
    L.append(f"台股組裝應收天數 {a['light']} " + "／".join(f"{c} " + ("→".join(str(p['ar_days']) for p in v.values()) or "缺") for c, v in a["by_co"].items()))
if "L3_tw_gm" in S:
    a = S["L3_tw_gm"]
    L.append(f"L3 台股毛利率 {a['period']} 上游 {a['upstream']}%／下游 {a['downstream']}%")
if "L5" in S:
    L.append("L5 ⚪ 觀察 " + "／".join(f"{k} {v['cur']}%（{v['prev']}）" for k, v in S["L5"].items()))
if "L4_smic" in S:
    a = S["L4_smic"]
    L.append(f"L4 中芯 {a['light']} 利用率 {a['util_prev']}→{a['util']}% 營收QoQ {a['rev_qoq']}%")
if "L4_bis" in S:
    a = S["L4_bis"]; q = a["last_full_quarter"]; c = a["classified"].get(q, {})
    L.append(f"L4 BIS {a['light']} {q} 相關規則 收緊{c.get('相關收緊', 0)}／放寬{c.get('相關放寬', 0)}／中國實體新增{c.get('中國實體新增', 0)}")
    for w in a["watch"]:
        L.append(f"   🟡 {w}")
if S["errors"]:
    L.append("")
    L.append("⚠️ 抽取失敗：")
    L += ["- " + e[:150] for e in S["errors"][:8]]
open(f"{IN}/summary.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
