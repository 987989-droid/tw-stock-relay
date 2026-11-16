#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 系統性風險警報（2026/11/16 建）。唯讀；不含任何持股與主題名單，皆由呼叫端以檔案／參數傳入。
起因：2026/11/09 起輝達新聞量暴增（日均約 9 則→27～138 則），11/13 費半 -3.43%，11/16 台股 -6.03%；
既有排程只做逐檔比對，大客戶事件被判成「未對應持股」，整個 AI 主題曝險沒有任何推播。

用法：python3 scripts/systemic_alert.py <repo 根目錄> <持股基準區原文 hold.txt> --ai 1513,1519,... [--asof YYYY-MM-DD]
訊號（全部機械判定）：
  一、美股隔夜（data/derived/us_overnight.json）：費半、NVDA、TSM ADR 單日跌幅，VIX 水準；資料日期落後即標「過期」
  二、大客戶／主題新聞量（data/daily/news/<日>.json）：各實體當日標題則數與負面詞則數，對前 20 個檔案的中位數比
  三、組合：AI 主題市值佔比、已跌破出場價未出場者、距出場價 5% 內者、AI 主題單日 -6%／-10% 的損益試算
輸出：=====<區名>===== 分段；最後 =====FLAGS===== 供排程判斷（不放進推播）。
結束碼：0 🟢 無訊號；10 🟡；11 🔴；4 持股基準核對碼不符；5 必要檔讀取失敗。美股資料過期不改結束碼，於 FLAGS 標 US_STALE=1。"""
import json, os, re, sys, glob, statistics, datetime as dt

args = sys.argv[1:]
NEWS_ONLY = "--news-only" in args          # 只跑新聞量判定，不需持股檔（供新聞判讀排程用）
R, HF = args[0], (None if NEWS_ONLY else args[1])
AI = set()
ASOF = None
if "--ai" in args: AI = {c.strip() for c in args[args.index("--ai") + 1].split(",") if c.strip()}
if "--asof" in args: ASOF = dt.date.fromisoformat(args[args.index("--asof") + 1])
TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = ASOF or dt.datetime.now(TZ).date()
P = lambda *a: os.path.join(R, *a)
def J(p):
    with open(P(p), encoding="utf-8") as f: return json.load(f)
def num(s):
    try: return float(str(s).replace(",", "").replace("+", "").strip())
    except (ValueError, TypeError): return None
def s(x): return str(x or "").strip()

LV = {"🟢": 0, "🟡": 1, "🔴": 2}
level = "🟢"
reasons = []
def bump(lv, why):
    global level
    if LV[lv] > LV[level]: level = lv
    reasons.append(f"{lv} {why}")

# ---- 持股基準（與 mine_check.py 同格式、同核對碼）----
H, chk = [], None
for l in ([] if NEWS_ONLY else open(HF, encoding="utf-8").read().splitlines()):
    l = l.strip()
    if not l or l.startswith(("```", "格式", "核對碼格式", "asof")): continue
    if l.startswith("chk:"): chk = l[4:].strip(); continue
    c, name, mk, sh, cost, avg, gate = l.split("|")
    H.append((c, name, mk, int(sh), round(float(cost)), float(avg), float(gate)))
got = "%d|%d|%d|%.2f" % (len(H), sum(h[3] for h in H), sum(h[4] for h in H), sum(h[6] for h in H))
if not NEWS_ONLY and got != chk: print("ABORT 持股基準核對碼不符：實得", got, "應為", chk); sys.exit(4)

# ---- 一、美股隔夜 ----
if not NEWS_ONLY: print("=====US=====")
def last_us_session(d):
    x = d - dt.timedelta(days=1)          # 台北日期的前一天＝美國最近一個交易日（週一→上週五）
    while x.weekday() >= 5: x -= dt.timedelta(days=1)
    return x
exp = last_us_session(TODAY)
us_stale = 0
try:
    U = J("data/derived/us_overnight.json"); L = {} if NEWS_ONLY else U.get("latest", {})
except Exception as e:
    print(f"美股隔夜檔讀取失敗：{str(e)[:80]}"); L = {}; us_stale = 1
TH = {"^SOX": ("費半", -3.0, -2.0), "NVDA": ("NVDA", -5.0, -3.0), "TSM": ("台積電ADR", -4.0, -2.5)}
for t, (nm, red, yel) in ({} if NEWS_ONLY else TH).items():
    x = L.get(t)
    if not x: print(f"{nm}：無資料"); us_stale = 1; continue
    d, chg = dt.date.fromisoformat(x["date"]), x["chg_1d_pct"]
    if ASOF and d >= TODAY: print(f"{nm}：回測模式略過（快照 {d:%m/%d} 晚於回測日）"); continue
    tag = "" if d >= exp else f"（過期：應為 {exp:%m/%d}）"
    if d < exp: us_stale = 1
    print(f"{nm} {d:%m/%d} {chg:+.2f}%{tag}")
    if d >= exp - dt.timedelta(days=3):      # 過期 3 日內的跌幅仍視為有效訊號（週末、資料延遲）
        if chg <= red: bump("🔴", f"{nm} {d:%m/%d} 單日 {chg:+.2f}%")
        elif chg <= yel: bump("🟡", f"{nm} {d:%m/%d} 單日 {chg:+.2f}%")
v = L.get("^VIX")
if v and not (ASOF and dt.date.fromisoformat(v["date"]) >= TODAY):
    print(f"VIX {v['date'][5:].replace('-', '/')} {v['close']}")
    if v["close"] >= 30: bump("🔴", f"VIX {v['close']}")
    elif v["close"] >= 25: bump("🟡", f"VIX {v['close']}")

# ---- 二、大客戶／主題新聞量 ----
print("=====NEWS=====")
ENT = {
    "輝達": r"輝達|NVIDIA|Nvidia|nvidia|黃仁勳|NVDA",
    "雲端大廠": r"微軟|Microsoft|谷歌|Google|Alphabet|亞馬遜|Amazon|AWS|Meta|臉書|OpenAI|甲骨文|Oracle|CoreWeave",
    "台積電": r"台積電|TSMC",
    "AI泡沫疑慮": r"AI.{0,6}(泡沫|疑慮|減速|降溫|退燒|見頂)|(泡沫|疑慮|減速|降溫).{0,6}AI",
}
NEG = r"辭|下台|撤換|離職|罷免|醜聞|間諜|共諜|調查|出口管制|禁令|管制|制裁|延後|延遲|遞延|砍單|下修|削減|暫停|訴訟|崩|重挫|暴跌|大跌|急殺|泡沫|疑慮|利空|升息|衝擊"
files = sorted(f for f in glob.glob(P("data/daily/news/*.json")) if os.path.basename(f)[:10] <= TODAY.isoformat())
if not files: print("新聞檔讀取失敗：無任何檔案"); sys.exit(5)
def counts(f):
    it = json.load(open(f, encoding="utf-8")).get("items", [])
    out = {}
    for k, rx in ENT.items():
        hit = [x for x in it if re.search(rx, s(x.get("t")))]
        neg = [x for x in hit if re.search(NEG, s(x.get("t")))]
        out[k] = (len(hit), len(neg), neg)
    return out, len(it)
cur_f = files[-1]
cur, n_all = counts(cur_f)
hist = [counts(f)[0] for f in files[-21:-1]]
cur_day = os.path.basename(cur_f)[:10]
stale_news = cur_day < (TODAY - dt.timedelta(days=1)).isoformat()
print(f"新聞檔 {cur_day}（{n_all} 則）" + ("（過期）" if stale_news else ""))
samples = []
for k in ENT:
    n, ng, negs = cur[k]
    base = statistics.median([h[k][0] for h in hist]) if hist else 0
    bneg = statistics.median([h[k][1] for h in hist]) if hist else 0
    ratio = n / max(base, 1)
    print(f"{k}：標題 {n} 則（前 20 檔中位數 {base:g}，{ratio:.1f} 倍）；負面詞 {ng} 則（中位數 {bneg:g}）")
    if (n >= 20 and ratio >= 3) or ng >= max(8, 4 * max(bneg, 1)):
        bump("🔴", f"{k}新聞暴量：{n} 則（常態 {base:g}）、負面 {ng} 則")
    elif (n >= 12 and ratio >= 2) or ng >= max(4, 3 * max(bneg, 1)):
        bump("🟡", f"{k}新聞增量：{n} 則（常態 {base:g}）、負面 {ng} 則")
    if ng and LV[level] >= 1: samples += [(k, x) for x in negs[:3]]
if samples:
    print("負面標題（各實體最多 3 則）：")
    seen = set()
    for k, x in samples:
        if x["t"] in seen: continue
        seen.add(x["t"]); print(f"  [{k}] {x['t']} {x.get('u', '')}")

if NEWS_ONLY:
    print("=====LEVEL=====")
    print(level + " " + ("；".join(reasons) if reasons else "無系統性訊號"))
    sys.exit({"🟢": 0, "🟡": 10, "🔴": 11}[level])
# ---- 三、組合曝險 ----
print("=====PORT=====")
q = {}
try:
    for x in J("data/latest/quotes_listed.json"):
        q[s(x["Code"])] = (num(x["ClosingPrice"]), s(x["Date"]))
    for x in J("data/latest/quotes_otc.json"):
        q[s(x["SecuritiesCompanyCode"])] = (num(x["Close"]), s(x["Date"]))
except Exception as e:
    print(f"收盤檔讀取失敗：{str(e)[:80]}"); sys.exit(5)
tot = ai_v = 0.0; rows, miss = [], []
for c, name, mk, sh, cost, avg, gate in H:
    px, d = q.get(c, (None, ""))
    if not px: miss.append(c); continue
    v = px * sh; tot += v
    if c in AI: ai_v += v
    rows.append((c, name, sh, cost, px, d, gate, v))
dates = sorted({r[5] for r in rows})
print(f"報價日 {'、'.join(dates)}（非即時、可能延遲）" + (f"；缺價 {','.join(miss)}" if miss else ""))
if tot:
    print(f"組合市值 {tot:,.0f}；AI 主題 {len(AI & {r[0] for r in rows})} 檔市值 {ai_v:,.0f}，佔 {ai_v / tot * 100:.1f}%")
    print(f"AI 主題單日 -6% 試算 {-ai_v * 0.06:,.0f}；-10% 試算 {-ai_v * 0.10:,.0f}")
br = [r for r in rows if r[4] < r[6]]
near = [r for r in rows if r[4] >= r[6] and (r[4] / r[6] - 1) < 0.05]
if br:
    bv = sum(r[7] for r in br)
    print(f"已跌破出場價、尚未出場 {len(br)} 檔，市值 {bv:,.0f}（佔 {bv / tot * 100:.1f}%），損益 {sum(r[7] - r[3] for r in br):,.0f}：")
    for r in sorted(br, key=lambda r: r[4] / r[6]):
        print(f"  {r[1]}({r[0]}) 收 {r[4]:g}／出場 {r[6]:g}（{(r[4] / r[6] - 1) * 100:+.1f}%）")
if near:
    print("距出場價 5% 內：" + "、".join(f"{r[1]}({r[0]}) 收 {r[4]:g}／出場 {r[6]:g}" for r in near))

print("=====LEVEL=====")
print(level + " " + ("；".join(reasons) if reasons else "無系統性訊號"))
print("=====FLAGS=====")
print(f"LEVEL={level} US_STALE={us_stale} NEWS_STALE={int(stale_news)} BREACH={len(br)} AI_PCT={ai_v / tot * 100 if tot else 0:.1f}")
sys.exit({"🟢": 0, "🟡": 10, "🔴": 11}[level])
