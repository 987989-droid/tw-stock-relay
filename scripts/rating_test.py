"""買賣評級測試期（2026/11/12–12/12）每日判定。唯讀；不含任何持股或追蹤清單，兩者由呼叫端以檔案傳入。
用法：python3 scripts/rating_test.py <repo 根目錄> <名單檔> <持股基準區原文 hold.txt> [附加 json：void、wl_chk]（舊格式持股 json 仍可用）
結束碼：0 正常；3 中繼批次過舊；4 持股或名單核對不符。"""
import json, os, sys, subprocess, datetime as dt
R, WL, HF = sys.argv[1], sys.argv[2], sys.argv[3]
TZ = dt.timezone(dt.timedelta(hours=8)); now = dt.datetime.now(TZ)
J = lambda p: json.load(open(os.path.join(R, p), encoding="utf-8"))
_raw = open(HF, encoding="utf-8").read()
import re as _re
_wl = list(dict.fromkeys(_re.findall(r"(?<!\d)\d{4}(?!\d)", open(WL, encoding="utf-8").read())))
if _raw.lstrip().startswith("{"):
    # 舊格式：持股 json（含 void、chk 六欄）
    H = json.loads(_raw); hold, void = H["hold"], H["void"]
    _chk = [len(hold), sum(h["sh"] for h in hold.values()), sum(h["cost"] for h in hold.values()), round(sum(h["gate"] for h in hold.values()), 2), len(_wl), sum(map(int, _wl))]
    if _chk != H["chk"]:
        print(f"ABORT 持股或名單抄寫有誤：實得 {_chk}，應為 {H['chk']}"); sys.exit(4)
    FOOT = FOOT
else:
    # 新格式（2026/11/14）：持股基準檔的機器讀取區原文（代號|名稱|市場|股數|成本|均價|出場價＋chk），第四參數為 {"void":{}, "wl_chk":[檔數, 代號和]}
    X = json.load(open(sys.argv[4], encoding="utf-8")) if len(sys.argv) > 4 else {}
    void, hold, chk, asof = X.get("void", {}), {}, None, ""
    for l in _raw.splitlines():
        l = l.strip()
        if not l or l.startswith(("```", "格式", "核對碼格式")): continue
        if l.startswith("asof"): asof = l.split(":", 1)[1].strip(); continue
        if l.startswith("chk:"): chk = l[4:].strip(); continue
        c, _n, _m, sh, cost, _a, gate = l.split("|")
        hold[c] = dict(sh=int(sh), cost=round(float(cost)), gate=float(gate))
    got = "%d|%d|%d|%.2f" % (len(hold), sum(h["sh"] for h in hold.values()), sum(h["cost"] for h in hold.values()), sum(h["gate"] for h in hold.values()))
    if got != chk:
        print(f"ABORT 持股或名單抄寫有誤：持股基準核對碼實得 {got}，應為 {chk}"); sys.exit(4)
    if X.get("wl_chk") and [len(_wl), sum(map(int, _wl))] != X["wl_chk"]:
        print(f"ABORT 持股或名單抄寫有誤：名單實得 {[len(_wl), sum(map(int, _wl))]}，應為 {X['wl_chk']}"); sys.exit(4)
    FOOT = f"持股基準：{asof}。持股由成交回報帳本每個交易日清晨自動入帳，買賣後不必手動更新"
def md(s):
    s = str(s).replace("-", "")
    if len(s) == 7: s = str(int(s[:3]) + 1911) + s[3:]
    return f"{s[4:6]}/{s[6:8]}" if len(s) == 8 else str(s)
idx = J("data/latest.json")
g = dt.datetime.fromisoformat(idx["generated_at_taipei"]).astimezone(TZ)
if (now - g).total_seconds() > 50 * 3600:
    print(f"ABORT 中繼每日批次過舊：最後產生 {g:%m-%d %H:%M}（超過 50 小時）"); sys.exit(3)
q = {}
for x in J("data/latest/quotes_listed.json"):
    try: q[x["Code"].strip()] = (float(x["ClosingPrice"].replace(",", "")), md(x["Date"]), x["Name"].strip())
    except Exception: pass
for x in J("data/latest/quotes_otc.json"):
    try: q[x["SecuritiesCompanyCode"].strip()] = (float(x["Close"].replace(",", "")), md(x["Date"]), x["CompanyName"].strip())
    except Exception: pass
judge = J("data/derived/judge.json")["stocks"]
th = J("data/derived/market_daily.json")
tnx = sorted(th["yf_close"].get("^TNX", {}).items())
t = th["thermo"]
L, sell, near, keep, miss = [], [], [], [], []
for c, h in hold.items():
    if c not in q: miss.append(c); continue
    px, d, nm = q[c]; gate = h["gate"]; gap = (px / gate - 1) * 100; pnl = (px * h["sh"] / h["cost"] - 1) * 100
    base = f"{c} {nm}｜收 {px:g}（{d}）｜閘門 {gate:g}｜損益 {pnl:+.1f}%"
    if c in void: sell.append((c, f"⚫ 賣 {base}｜出場理由①作廢條件成立：{void[c]}"))
    elif px < gate: sell.append((c, f"⚫ 賣 {base}｜低於閘門 {gap:.1f}%｜出場理由②價格閘門"))
    else:
        why = []
        j = judge.get(c) or {}
        if j.get("營業利益_當季") is not None and j["營業利益_當季"] < 0: why.append(f"{j['period']}單季本業虧損")
        if j.get("業外佔稅前_當季") is not None and j["業外佔稅前_當季"] >= 50: why.append(f"{j['period']}業外佔稅前{j['業外佔稅前_當季']:.0f}%")
        if j.get("營現_累計") is not None and j["營現_累計"] < 0: why.append(f"{j['period']}累計營業現金流為負")
        if gap < 5: near.append((c, f"🟡 續抱（貼閘門 +{gap:.1f}%）{base}" + ("｜" + "、".join(why) if why else "")))
        else: keep.append((c, f"{'🟡' if why else '🟢'} 續抱 {base}｜距閘門 +{gap:.1f}%" + ("｜" + "、".join(why) if why else "")))
out_codes = {c for c, _ in sell}
# ---- 水位與美債 ----
fs, f5, vix = t.get("foreign_streak_days"), t.get("foreign_net_5d_e8"), t.get("vix")
if (fs is not None and fs <= -5 and f5 is not None and f5 < 0) or (vix is not None and vix >= 30): water = "🔴"
elif fs is not None and fs >= 3 and vix is not None and vix < 20: water = "🟢"
else: water = "🟡"
wl = f"水位 {water}｜外資連{'買' if (fs or 0) > 0 else '賣'} {abs(fs or 0)} 日、近 5 日 {f5:+.1f} 億（至 {md(t.get('twse_last_date'))}）｜VIX {vix}（{md(t.get('vix_date'))}）"
bond = "⚪ 美債：殖利率資料不足，不判定"
if len(tnx) >= 21:
    y0, y5, y20 = tnx[-1][1], tnx[-6][1], tnx[-21][1]
    ok = y0 < y5 and y0 < y20
    bond = (f"{'🟢 長天期美債可加碼（仍須寫四欄）' if ok else '🔴 長天期美債不加碼'}｜美 10 年期殖利率 {y0:.3f}%（{md(tnx[-1][0])}），5 日前 {y5:.3f}%、20 日前 {y20:.3f}%"
            + ("" if ok else "｜條件＝同時低於 5 日前與 20 日前，未成立"))
# ---- 買進篩選（中繼 screen.py，唯讀）----
buy, watch, excl, bnote = [], [], [], ""
p = subprocess.run([sys.executable, os.path.join(R, "scripts/screen.py"), R, WL, "--json"], capture_output=True, text=True)
if p.returncode != 0:
    bnote = "⚠️ 買進篩選未完成：" + (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f"結束碼 {p.returncode}")
else:
    S = json.loads(p.stdout); m = S["meta"]
    if m.get("stale"): bnote = "⚠️ 買進篩選資料未更新，今日不出名單：" + "；".join(m["stale"])
    else:
        bnote = f"名單 {m['wl']} 檔 → 營收加速且落後大盤（嚴格）{m['strict']} 檔｜營收 {m['months_last'][0]}–{m['months_last'][-1]}｜損益 {m['is_last']}"
        for r in sorted(S["strict"], key=lambda r: -r["acc"]):
            c = r["code"]; mm = (r.get("m") or {}).get("last") or {}
            s = (f"{c} {r['name']}｜收 {r['close']:g}（{md(r['date'])}）｜營收YoY {r['yoy_prev']:.1f}%→{r['yoy']:.1f}%｜落後大盤 {r['rel3m']:.1f}%"
                 + (f"｜毛利率 {mm['gm']:.1f}%" if mm.get("gm") is not None else ""))
            if c in out_codes: excl.append(f"{c} {r['name']}")
            elif r["flag"] == "⚫": excl.append(f"{c} {r['name']}（地雷：{r['why'][0][:30]}）")
            elif r["flag"] == "🟡": watch.append(f"🟡 觀察 {s}｜疑點：" + "；".join(w[:40] for w in r["why"][:2]))
            else:
                tag = "加碼候選" if c in hold else "買進候選"
                buy.append((c, f"🟢 {tag} {s}｜參考閘門（收盤×0.85）{r['close'] * 0.85:.2f}"))
can_buy = water != "🔴"
one = f"賣 {len(sell)} 檔｜續抱 {len(near) + len(keep)} 檔｜" + (f"買進候選 {len(buy)} 檔" if can_buy else f"水位🔴 今日不買（候選 {len(buy)} 檔列觀察）")
L += [f"買賣判定（測試期至 12/12）{now:%Y-%m-%d}", one, "報價非即時、可能延遲；各行括號內為收盤日", "", "── 賣 ──"]
L += [s for _, s in sell] or ["無"]
L += ["", "── 續抱 ──"] + [s for _, s in near + keep]
if miss: L.append("⚠️ 查無報價：" + "、".join(miss))
L += ["", "── 買 ──", wl, bnote]
L += [s if can_buy else s.replace("🟢 買進候選", "🟡 觀察（水位🔴暫不買）").replace("🟢 加碼候選", "🟡 觀察（水位🔴暫不買）") for _, s in buy]
L += watch
if excl: L.append("排除：" + "、".join(excl))
L += ["候選只過了月營收、地雷、流動性三關；現金流與應收存貨未驗，下單前在對話說「查核 XXXX 買」，並寫齊四欄（預估機率由你填）", "", "── 美債 ──", bond]
for c in [k for k in hold if k.endswith("B")]:
    for grp in (sell, near, keep):
        for cc, s in grp:
            if cc == c: L.append(s)
L += ["", FOOT, "依你的規則與中繼資料機械判定；作廢條件逐條比對仍以每日地雷監測為準；不含目標價"]
print("\n".join(L))
print("=====SMS=====")
print(one)
print("賣：" + ("、".join(c for c, _ in sell) or "無"))
print(("買進候選：" if can_buy else "觀察（暫不買）：") + ("、".join(c for c, _ in buy) or "無"))
print(bond.split("｜")[0])
