#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跌幅拆解＋市場溫度計（2026/11/06 建；排程以 curl … | python3 - <代號…> 呼叫）。
名單由呼叫端以參數傳入，本檔不含任何持股。只讀中繼公開檔：
- data/derived/beta_alpha.json（每交易日更新：近 1 月報酬、相對大盤、β）
- data/derived/market_daily.json（溫度計）、market_t86_<日期>.json（上市個股法人買賣超）
拆解（近似法，非精確歸因）：大盤貢獻＝β×加權近 1 月報酬；個股自身＝實際報酬−大盤貢獻。
個股自身佔跌幅 ≥50% →「個股為主」，否則「大盤為主」。"""
import json, sys, urllib.request

B = "https://raw.githubusercontent.com/987989-droid/tw-stock-relay/main/data/derived/"
def J(name):
    with urllib.request.urlopen(B + name, timeout=60) as r:
        return json.load(r)

codes = [c for c in sys.argv[1:] if c.isdigit() and len(c) == 4]
ba = J("beta_alpha.json"); rows = {r["code"]: r for r in ba["rows"]}
md = J("market_daily.json"); th = md.get("thermo", {})
t86 = {}
if th.get("twse_last_date"):
    try: t86 = J(f"market_t86_{th['twse_last_date']}.json")["data"]
    except Exception: t86 = {}

L = []
for c in codes:
    r = rows.get(c)
    if not r or r.get("ret_1m") is None or r.get("beta") is None:
        L.append(f"拆解 {c}：資料不足（beta_alpha 無此檔或樣本不足）"); continue
    ri, rel, b = r["ret_1m"] * 100, r["rel_1m"] * 100, r["beta"]
    rm = ri - rel
    exp = b * rm
    res = ri - exp
    if ri >= 0:
        tag = "近1月未下跌"
    else:
        tag = "個股為主" if res / ri >= 0.5 else "大盤為主"
    L.append(f"拆解 {c}（至{r['last_date']}）：近1月 {ri:.1f}%＝大盤貢獻 {exp:.1f}%（β{b:.2f}×加權{rm:.1f}%）＋個股自身 {res:.1f}% → {tag}")
    if c in t86:
        f, t, a = t86[c]
        L.append(f"  法人 {th['twse_last_date'][4:6]}/{th['twse_last_date'][6:]}：外資 {f/1000:+,.0f} 張、投信 {t/1000:+,.0f} 張")
    elif r.get("market") == "otc":
        L.append("  法人：上櫃個股法人資料未納入")

def s(k, fmt="{:+.2f}"):
    v = th.get(k)
    return "—" if v is None else fmt.format(v)
if th:
    fs, ts = th.get("foreign_streak_days", 0), th.get("trust_streak_days", 0)
    fdesc = f"外資連{'買' if fs > 0 else '賣'}{abs(fs)}日" if fs else "外資今日持平"
    tdesc = f"投信連{'買' if ts > 0 else '賣'}{abs(ts)}日" if ts else "投信今日持平"
    d = th.get("twse_last_date") or ""
    L.append(f"溫度計 {d[4:6]}/{d[6:]}：{fdesc}（5日{s('foreign_net_5d_e8', '{:+,.1f}')}億）｜{tdesc}"
             f"（5日{s('trust_net_5d_e8', '{:+,.1f}')}億）｜融資5日{s('margin_chg_5d_pct')}%｜"
             f"加權5日{s('twii_chg_5d_pct')}%｜費半5日{s('sox_chg_5d_pct')}%｜美元兌台幣5日{s('usdtwd_chg_5d_pct')}%｜VIX {s('vix', '{:.1f}')}")
print("\n".join(L))
