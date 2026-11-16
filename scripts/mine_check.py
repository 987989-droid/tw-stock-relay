"""每日持股地雷監測的機械檢核（2026/11/16 自排程指令搬入）。唯讀；不含任何持股，持股由呼叫端以檔案傳入。
用法：python3 scripts/mine_check.py <repo 根目錄> <持股基準區原文 hold.txt>
輸出：以 =====<區名>===== 分段，供排程原樣照貼；最後 =====FLAGS===== 為排程判斷用（不放進推播）。
結束碼：0 正常；4 持股基準核對碼不符；5 核心檔（重訊／內部人）筆數不符或讀取失敗。
規則來源：使用者自訂監測規則（地雷監測排程指令 2026/09～11 各版），只做機械判定，不判讀論點、不評級。"""
import json, os, sys, datetime as dt
R, HF = sys.argv[1], sys.argv[2]
TZ = dt.timezone(dt.timedelta(hours=8)); now = dt.datetime.now(TZ)
P = lambda *a: os.path.join(R, *a)
def J(p):
    with open(P(p), encoding="utf-8") as f: return json.load(f)
def num(s):
    try: return float(str(s).replace(",", "").replace("+", "").replace("%", "").strip())
    except (ValueError, TypeError): return None
def s(x): return str(x or "").strip()

# ---- 持股基準 ----
H, chk, asof = [], None, ""
for l in open(HF, encoding="utf-8").read().splitlines():
    l = l.strip()
    if not l or l.startswith(("```", "格式", "核對碼格式")): continue
    if l.startswith("asof"): asof = l; continue
    if l.startswith("chk:"): chk = l[4:].strip(); continue
    c, name, mk, sh, cost, avg, gate = l.split("|")
    H.append((c, name, mk, int(sh), round(float(cost)), float(avg), float(gate)))
got = "%d|%d|%d|%.2f" % (len(H), sum(h[3] for h in H), sum(h[4] for h in H), sum(h[6] for h in H))
if got != chk: print("ABORT 持股基準核對碼不符：實得", got, "應為", chk); sys.exit(4)
NAME = {h[0]: h[1] for h in H}
STK = [h for h in H if not h[0].startswith("00")]
SC = {h[0] for h in STK}
FLAGS = {"PUSH": [], "NEW_BLACK": [], "CONT_BLACK": [], "VOID_HIT": []}
idx = J("data/latest.json")
print("=====HOLD=====")
print(asof)
print(f"個股 {len(STK)} 檔：" + " ".join(f"{h[0]}{h[1]}" for h in STK))

# ---- 一、重訊與內部人（核心，須對帳）＋回補 4 日 ----
print("=====CORE=====")
recon, core_bad = [], []
def daily_files(key):
    f = idx["files"][key]; out = [(f["path"], True)]
    base = os.path.basename(f["path"])[:-5]
    try: d0 = dt.date.fromisoformat(base)
    except ValueError: return out
    for i in range(1, 5):
        p = f"data/daily/{key}/{(d0 - dt.timedelta(days=i)).isoformat()}.json"
        if os.path.exists(P(p)): out.append((p, False))
    return out
seen, hits = set(), []
for key in ("material_listed", "material_otc", "insider_listed", "insider_otc"):
    for p, main in daily_files(key):
        try: rows = J(p)
        except Exception as e:
            if main: core_bad.append(f"{key} 讀取失敗：{str(e)[:80]}")
            continue
        if main:
            cnt = idx["files"][key].get("count"); recon.append(f"{len(rows)}/{cnt}")
            if cnt is not None and len(rows) != cnt: core_bad.append(f"{key} 索引{cnt}／實抓{len(rows)}")
        tag = "" if main else f"（回補 {p[-10:-5][-5:].replace('-', '/')}）"
        for x in rows:
            c = s(x.get("公司代號") or x.get("SecuritiesCompanyCode"))
            nm = s(x.get("公司名稱") or x.get("CompanyName"))
            if key.startswith("material"):
                subj = s(x.get("主旨 ") or x.get("主旨")).replace("\r\n", "").replace("\n", "")
                d = s(x.get("事實發生日") or x.get("發言日期"))
                k = (c, d, subj[:60])
                if k in seen: continue
                seen.add(k)
                hit = c in SC or (c == "6414" and any(w in subj for w in ("樺成", "背書保證", "Kontron")))
                if hit:
                    if c == "6414":  # 非持股，樺漢以帆宣股票擔保之融資後續：一律列出並推播，背書保證／Kontron 標紅
                        red = any(w in subj for w in ("背書保證", "Kontron")); FLAGS["PUSH"].append(c)
                    else:
                        red = any(w in subj for w in ("現金增資", "可轉換公司債", "轉換公司債", "海外存託憑證", "私募", "減資", "會計師", "稽核主管", "財務主管", "會計主管", "重編", "資安", "停止買賣", "變更交易", "下市"))
                    hits.append((0 if red else 1, f"{'🔴 ' if red else ''}{nm}({c}) {d[3:5]}/{d[5:7]} {subj[:90]}{tag}"))
                    if red: FLAGS["PUSH"].append(c)
            else:
                k = (c, s(x.get("姓名")), s(x.get("有效轉讓期間")))
                if k in seen: continue
                seen.add(k)
                if c in SC:
                    have, sell = num(x.get("目前持有股數-自有持股")), num(x.get("預定轉讓總股數-自有持股"))
                    pct = (sell / have * 100) if have else None
                    red = pct is not None and pct >= 20 or c == "8227"
                    hits.append((0 if red else 1, f"{'🔴 ' if red else ''}{nm}({c}) {s(x.get('姓名'))}·{s(x.get('申報人身分') or x.get('申請人身分'))} 轉讓 {int(sell or 0):,} 股（佔持有 {pct:.1f}%）期間 {s(x.get('有效轉讓期間'))}{tag}" if pct is not None else f"{nm}({c}) {s(x.get('姓名'))} 申報轉讓{tag}"))
                    FLAGS["PUSH"].append(c)
if core_bad:
    print("CORE_FAIL " + "；".join(core_bad)); sys.exit(5)
for _, t in sorted(hits): print(t)
if not hits: print("重訊與內部人：無命中")
print("對帳 OK(" + "·".join(recon) + ")")

# ---- 二、狀態清單（新上榜才推）----
print("=====STATUS=====")
ST = {"control_suspend_listed": "停止買賣", "control_altered_listed": "變更交易", "penalty_listed": "金管會裁罰",
      "disclosure_violation_listed": "違反資訊申報", "control_change_listed": "經營權異動", "shortfall_listed": "董監持股不足"}
st_out = []
for key, lab in ST.items():
    try:
        f = idx["files"][key]; cur = J(f["path"])
        d0 = dt.date.fromisoformat(os.path.basename(f["path"])[:-5]); prev = None
        for i in range(1, 6):
            p = f"data/daily/{key}/{(d0 - dt.timedelta(days=i)).isoformat()}.json"
            if os.path.exists(P(p)): prev = J(p); break
        code = lambda x: s(x.get("公司代號") or x.get("股票代號"))
        cs = {code(x) for x in cur} & SC
        ps = {code(x) for x in prev} & SC if prev is not None else None
        for c in sorted(cs):
            if ps is None: st_out.append(f"{lab}：{NAME[c]}({c}) 首日建檔，趨勢待明日")
            elif c in ps: st_out.append(f"{lab}：{NAME[c]}({c}) 已在榜")
            else: st_out.append(f"🔴 {lab}：{NAME[c]}({c}) 新上榜"); FLAGS["PUSH"].append(c)
    except Exception as e:
        st_out.append(f"{lab}：未取得（{str(e)[:60]}）")
print("\n".join(st_out) if st_out else "狀態清單：無持股在榜（僅含上市；上櫃狀態變更靠重訊主旨辨識）")

# ---- 三、月頻：設質（逐人、依姓名去重）----
print("=====PLEDGE=====")
def latest_two(d):
    fs = sorted(f for f in os.listdir(P(d)) if f.endswith(".json"))
    return fs[-1][:-5] if fs else None, fs[-2][:-5] if len(fs) > 1 else None
def pledge_map(mk, ym):
    out = {}
    if not ym: return out
    for x in J(f"data/monthly/pledge_{mk}/{ym}.json"):
        c = s(x.get("公司代號"))
        if c not in SC: continue
        nm = s(x.get("姓名")); out.setdefault(c, {})
        if nm in out[c]: continue
        out[c][nm] = (s(x.get("職稱")), num(x.get("目前持股")) or 0, num(x.get("設質股數")) or 0)
    return out
pl_out = []
try:
    for mk in ("listed", "otc"):
        ym, ym0 = latest_two(f"data/monthly/pledge_{mk}")
        cur, prev = pledge_map(mk, ym), pledge_map(mk, ym0)
        for c in sorted(set(cur) | {h[0] for h in STK if h[2] == mk}):
            people = cur.get(c, {})
            if not people: continue
            tot_h = sum(v[1] for v in people.values()); tot_p = sum(v[2] for v in people.values())
            for nm, (title, have, pl) in people.items():
                r = pl / have * 100 if have else 0
                if c == "6196" and "樺成" in nm:
                    p0 = prev.get(c, {}).get(nm)
                    line = f"帆宣(6196) 樺成 持股 {int(have):,} · 設質 {int(pl):,}（前期 {int(p0[2]):,}）" if p0 else f"帆宣(6196) 樺成 持股 {int(have):,} · 設質 {int(pl):,}（無前期）"
                    if p0 and have < p0[1]: line = "⚫ " + line + "\n   → 觸及作廢條件：樺成持股減少或申報轉讓帆宣"; FLAGS["PUSH"].append(c); FLAGS["VOID_HIT"].append(c)
                    elif pl > 41_700_000: line = "⚫ " + line + "\n   → 觸及作廢條件：樺成設質超過公告擔保範圍 41,700,000 股"; FLAGS["PUSH"].append(c); FLAGS["VOID_HIT"].append(c)
                    pl_out.append(line); continue
                if c == "8227" and pl > 0:
                    pl_out.append(f"🔴 巨有科技(8227) {nm}·{title} 設質 {int(pl):,} 股（{r:.2f}%）\n   → 觸及作廢條件：內部人質押開始出現"); FLAGS["PUSH"].append(c); FLAGS["VOID_HIT"].append(c); continue
                if c == "3105" and "董事長" in title and r > 50:
                    pl_out.append(f"🔴 穩懋(3105) {nm}·{title} 設質 {r:.2f}%\n   → 觸及作廢條件：董事長設質比升破50%"); FLAGS["PUSH"].append(c); FLAGS["VOID_HIT"].append(c); continue
                if r < 30: continue
                p0 = prev.get(c, {}).get(nm)
                if p0 is None: pl_out.append(f"{NAME[c]}({c}) {nm}·{title} 設質 {r:.2f}%（趨勢待下期）"); continue
                r0 = p0[2] / p0[1] * 100 if p0[1] else 0
                trend = "新增" if p0[2] == 0 else ("上升" if r - r0 >= 0.005 else ("持平" if abs(r - r0) < 0.005 else "下降"))
                red = trend == "新增" or r - r0 >= 5
                pl_out.append(f"{'🔴 ' if red else ''}{NAME[c]}({c}) {nm}·{title} 設質 {r:.2f}%（前期 {r0:.2f}%，{trend}）" + ("" if red else "，已在榜"))
                if red: FLAGS["PUSH"].append(c)
        print(f"（{mk} {ym} 對 {ym0}）")
except Exception as e:
    pl_out.append(f"設質：未取得（{str(e)[:80]}）")
print("\n".join(pl_out) if pl_out else "設質：無人達 30%")

# ---- 三之二、月營收 ----
print("=====REVENUE=====")
judge = {}
try: judge = J("data/derived/judge.json")["stocks"]
except Exception: pass
rv_out = []
try:
    for mk in ("listed", "otc"):
        ym, ym0 = latest_two(f"data/monthly/revenue_{mk}")
        cur = {s(x.get("公司代號")): x for x in J(f"data/monthly/revenue_{mk}/{ym}.json")}
        prev = {s(x.get("公司代號")): x for x in J(f"data/monthly/revenue_{mk}/{ym0}.json")} if ym0 else {}
        for h in STK:
            c = h[0]
            if h[2] != mk: continue
            x = cur.get(c)
            if x is None: rv_out.append(f"{NAME[c]}({c})：中繼月營收檔缺此檔（{mk} {ym} 共 {len(cur)} 筆）"); continue
            yoy, acc = num(x.get("營業收入-去年同月增減(%)")), num(x.get("累計營業收入-前期比較增減(%)"))
            acc0 = num(prev.get(c, {}).get("累計營業收入-前期比較增減(%)")) if c in prev else None
            if c in ("3105", "8227"):
                line = f"{NAME[c]}({c}) {ym} YoY {yoy:+.2f}%、累計 {acc:+.2f}%"
                if acc is not None and acc < 0 and acc0 is not None and acc0 >= 0:
                    line = "🔴 " + line + "\n   → 觸及作廢條件：累計營收 YoY 由正轉負"; FLAGS["PUSH"].append(c); FLAGS["VOID_HIT"].append(c)
                rv_out.append(line); continue
            if yoy is not None and yoy <= -20:
                j = judge.get(c, {})
                gm = j.get("毛利率_當季")
                rv_out.append(f"🔴 {NAME[c]}({c}) {ym} YoY {yoy:+.2f}%（累計 {acc:+.2f}%）" + (f"｜{j.get('period')} 單季毛利率 {gm:.2f}%：營收衰退須以毛利率覆核，若毛利率上升可能是低毛利業務退出" if gm is not None else ""))
                FLAGS["PUSH"].append(c)
            elif acc is not None and acc < 0:
                rv_out.append(f"{NAME[c]}({c}) {ym} 累計 {acc:+.2f}%（為負，列出不推播）")
except Exception as e:
    rv_out.append(f"月營收：未取得（{str(e)[:80]}）")
print("\n".join(rv_out) if rv_out else "月營收：無低於門檻")

# ---- 四、季頻（讀 judge.json，上市上櫃都涵蓋，單季數）----
print("=====QUARTERLY=====")
q_out = []
for h in STK:
    c = h[0]; j = judge.get(c)
    if not j: q_out.append(f"{NAME[c]}({c})：judge.json 無此檔（季報未建檔）"); continue
    oi, pbt, ni, ex = j.get("營業利益_當季"), j.get("稅前_當季"), j.get("稅後_當季"), j.get("業外佔稅前_當季")
    why = []
    if oi is not None and oi < 0 and ((pbt or 0) > 0 or (ni or 0) > 0): why.append(f"本業虧損業外撐獲利（營業利益 {oi:,.0f}／稅前 {pbt:,.0f}）")
    if ex is not None and ex >= 50 and (pbt or 0) > 0: why.append(f"業外佔稅前 {ex:.2f}%（須拆來源：利息股利＝結構性；評價處分匯兌＝一次性）")
    if c == "8227" and oi is not None and oi < 0: why.append("→ 觸及作廢條件：單季營業利益轉負"); FLAGS["VOID_HIT"].append(c)
    if why:
        q_out.append(f"🔴 {NAME[c]}({c}) {j.get('period')} 單季：" + "；".join(why)); FLAGS["PUSH"].append(c)
print("\n".join(q_out) if q_out else "季頻（單季）：無紅旗")

# ---- 五、價格閘門 ----
print("=====GATE=====")
try:
    fl, fo = idx["files"]["quotes_listed"], idx["files"]["quotes_otc"]
    L, O = J(fl["path"]), J(fo["path"])
    QL = {s(x["Code"]): (num(x["ClosingPrice"]), num(x.get("Change")), s(x["Date"])) for x in L}
    QO = {s(x["SecuritiesCompanyCode"]): (num(x["Close"]), num(x.get("Change")), s(x["Date"])) for x in O}
    dl, do = max(v[2] for v in QL.values()), max(v[2] for v in QO.values())
    new, cont, near, miss = [], [], [], []
    for c, name, mk, sh, cost, avg, gate in H:
        q = (QL if mk == "listed" else QO).get(c) or (QO if mk == "listed" else QL).get(c)
        if not q or q[0] is None: miss.append(c); continue
        px, chg, d = q
        if px < gate:
            if chg is not None and px - chg < gate: cont.append(f"{name}({c}) 收 {px:g}／出場 {gate:.2f}"); FLAGS["CONT_BLACK"].append(c)
            else: new.append(f"⚫ {name}({c}) 收 {px:g}（{d}）< 出場價 {gate:.2f} · 距成本 {(px / avg - 1) * 100:+.1f}%"); FLAGS["NEW_BLACK"].append(c)
        elif px < gate * 1.05:
            near.append(f"🟡 {name}({c}) 收 {px:g}（{d}）貼近出場價 {gate:.2f}（高 {(px / gate - 1) * 100:.1f}%）")
        if c == "6196" and px < 527.58:
            near.append(f"🟡 {name}(6196) 收 {px:g}（{d}）< 527.58｜樺成擔保品等值價 479.62×1.10")
    for x in new: print(x)
    if cont: print(f"⚫ 持續跌破 {len(cont)} 檔（前一交易日已低於出場價）：" + "、".join(cont))
    for x in near: print(x)
    if miss: print("價格閘門取不到報價：" + " ".join(miss))
    if not (new or cont): print("價格閘門：無跌破")
    print(f"報價日 上市{dl}／上櫃{do}" + ("（兩市場報價日不同）" if dl != do else ""))
except Exception as e:
    print("GATE_FAIL 價格閘門未取得：" + str(e)[:200])

print("=====FLAGS=====")
for k, v in FLAGS.items(): print(k, " ".join(dict.fromkeys(v)) or "無")
