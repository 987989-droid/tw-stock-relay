"""多模型交叉驗證（2026/11/15 建）。

目的：燈號 parser（judge_parse.py）從 MOPS 原表抽出的關鍵數字，另請兩家不同廠商的模型
      各自獨立從同一份原表抽一次，三方對帳；分歧欄位即為需要人工（Claude）仲裁的盲點。
模型：GitHub Models（models.github.ai），以 runner 的 GITHUB_TOKEN 呼叫（workflow 須給 models: read），
      免額外金鑰。執行時先讀模型目錄，依偏好清單各挑一家廠商（A 組 OpenAI、B 組非 OpenAI）。
輸入：data/derived/judge.json（每檔期別）＋ data/mops/<期>/<代號>_t164sb03/04/05.html（本機 checkout）。
輸出：data/derived/xval.json（逐檔逐欄 parser／A／B 與是否一致）、data/derived/_xval_status.json。
不讀任何持股清單：對象＝judge.json 已有的代號。
紀律：單檔失敗不影響其他檔；不重試；呼叫間隔遵守免費額度（高階模型每分鐘 10 次）。
"""
import json, os, re, sys, time, datetime, html as htmlmod, urllib.request, urllib.error

TOKEN = os.environ.get("GITHUB_TOKEN", "")
CAT = "https://models.github.ai/catalog/models"
INF = "https://models.github.ai/inference/chat/completions"
PREF_A = ["openai/gpt-4.1", "openai/gpt-4o", "openai/gpt-4.1-mini", "openai/gpt-4o-mini"]
PREF_B = ["deepseek/DeepSeek-V3-0324", "meta/Llama-4-Maverick-17B-128E-Instruct-FP8",
          "meta/Llama-3.3-70B-Instruct", "mistral-ai/mistral-medium-2505", "xai/grok-3-mini",
          "mistral-ai/Mistral-Large-2411", "cohere/cohere-command-a"]
SLEEP = 7
CTX_LIMIT = 9000          # 免費額度單次輸入約 8000 token，原表先壓成精簡列

FIELDS = {   # 欄位: (judge.json 鍵, 定義)
    "營收_當季":   ("營收_當季",   "綜合損益表「營業收入合計」本年當季金額"),
    "營業利益_當季": ("營業利益_當季", "綜合損益表「營業利益（損失）」本年當季金額"),
    "稅前_當季":   ("稅前_當季",   "綜合損益表「繼續營業單位稅前淨利（淨損）」（無此列則「稅前淨利（淨損）」）本年當季金額"),
    "稅後_當季":   ("稅後_當季",   "綜合損益表「本期淨利（淨損）」本年當季金額"),
    "EPS_當季":    ("EPS_當季",    "綜合損益表「基本每股盈餘」本年當季（元）"),
    "營現_累計":   ("營現_累計",   "現金流量表「營業活動之淨現金流入（流出）」本期累計金額"),
    "應收_期末":   ("應收_期末",   "資產負債表「應收帳款淨額」（無此列則「應收帳款」）本期期末金額，不含關係人"),
    "存貨_期末":   ("存貨_期末",   "資產負債表「存貨」本期期末金額"),
}
KEEP = re.compile(r"營業收入|營業成本|營業毛利|營業費用|營業利益|營業外|稅前|所得稅|本期淨利|每股盈餘|"
                  r"營業活動之淨現金|營運產生|應收帳款|存貨|合計|會計項目|民國|單位")


def http_json(url, data=None):
    h = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json",
         "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"}
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def rows(path):
    """MOPS 表格 HTML → 『科目<TAB>數值…』精簡列。"""
    if not os.path.exists(path):
        return []
    h = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", h):
        cells = [re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
                 for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        cells = [c for c in cells if c]
        if cells:
            out.append("\t".join(cells))
    return out


def context(co, per):
    parts = []
    for rpt, name in (("t164sb04", "綜合損益表"), ("t164sb05", "現金流量表"), ("t164sb03", "資產負債表")):
        r = rows(f"data/mops/{per}/{co}_{rpt}.html")
        keep = [x for x in r if KEEP.search(x.split("\t")[0])]
        parts.append(f"## {name}\n" + "\n".join(keep))
    txt = "\n\n".join(parts)
    return txt[:CTX_LIMIT]


def ask(model, co, per, ctx):
    spec = "\n".join(f'- "{k}": {v[1]}' for k, v in FIELDS.items())
    prompt = (f"以下是台灣上市櫃公司 {co} 於 {per} 的合併財務報表節錄（MOPS 原表，金額單位新台幣仟元，"
              f"每列為『科目、各期欄位』；綜合損益表欄位順序通常為：本年當季、去年當季、本年累計、去年累計，"
              f"每個金額後可能跟一個百分比欄，百分比不是金額）。\n請只根據表格內容抽出下列欄位，"
              f"只回傳一個 JSON 物件，數值用數字（負數用負號、不要千分位），找不到填 null，不要任何說明：\n{spec}\n\n{ctx}")
    j = http_json(INF, {"model": model, "temperature": 0, "max_tokens": 600,
                        "messages": [{"role": "system", "content": "你是嚴謹的財報數字抽取器，只輸出 JSON。"},
                                     {"role": "user", "content": prompt}]})
    txt = j["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {"_raw": txt[:300]}


def num(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def same(a, b, eps):
    return a is not None and b is not None and abs(a - b) <= eps


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    status = {"run_at_utc": now, "ok": False}
    # 模型目錄端點 2026/11/15 實測回空內容（非 JSON）→ 不依賴目錄，直接依偏好清單逐一試呼叫
    def pick(prefs):
        tried = []
        for m in prefs:
            try:
                j = http_json(INF, {"model": m, "max_tokens": 5, "messages": [{"role": "user", "content": "回覆 OK"}]})
                if j.get("choices"):
                    return m, tried
                tried.append(f"{m}: 無 choices")
            except urllib.error.HTTPError as e:
                tried.append(f"{m}: HTTP {e.code} {e.read()[:120]!r}")
            except Exception as e:
                tried.append(f"{m}: {e!r}"[:160])
            time.sleep(3)
        return None, tried
    mA, triedA = pick(PREF_A)
    mB, triedB = pick(PREF_B)
    status.update({"model_a": mA, "model_b": mB, "tried_a": triedA, "tried_b": triedB})
    if not (mA and mB):
        status["error"] = "兩家不同廠商的模型未能都呼叫成功"
        json.dump(status, open("data/derived/_xval_status.json", "w"), ensure_ascii=False, indent=1)
        print(json.dumps(status, ensure_ascii=False)); sys.exit(1)

    judge = json.load(open("data/derived/judge.json", encoding="utf-8"))
    out = {"generated_at_utc": now, "judge_generated_at_utc": judge.get("generated_at_utc"),
           "model_a": mA, "model_b": mB, "stocks": {}, "divergent": []}
    calls = fails = 0
    for co, st in sorted(judge["stocks"].items()):
        per = st.get("period")
        ctx = context(co, per)
        rec = {"name": st.get("name"), "period": per, "ctx_chars": len(ctx), "fields": {}, "errors": []}
        ans = {}
        for tag, model in (("a", mA), ("b", mB)):
            try:
                ans[tag] = ask(model, co, per, ctx); calls += 1
            except Exception as e:
                ans[tag] = {}; fails += 1; rec["errors"].append(f"{tag}:{e!r}"[:200])
            time.sleep(SLEEP)
        for f, (jk, _) in FIELDS.items():
            p, a, b = num(st.get(jk)), num(ans["a"].get(f)), num(ans["b"].get(f))
            eps = 0.011 if f == "EPS_當季" else 1.0
            agree_a, agree_b = same(p, a, eps), same(p, b, eps)
            verdict = ("全一致" if agree_a and agree_b else
                       "parser 與 A、B 皆不同" if (not agree_a and not agree_b and same(a, b, eps)) else
                       "單一模型不同" if (agree_a or agree_b) else "三方皆不同")
            rec["fields"][f] = {"parser": p, "a": a, "b": b, "verdict": verdict}
            if verdict in ("parser 與 A、B 皆不同", "三方皆不同"):
                out["divergent"].append({"co": co, "field": f, "parser": p, "a": a, "b": b, "verdict": verdict})
        out["stocks"][co] = rec
        print(co, per, {f: v["verdict"] for f, v in rec["fields"].items()}, rec["errors"] or "")

    json.dump(out, open("data/derived/xval.json", "w"), ensure_ascii=False, indent=1)
    status.update({"ok": fails == 0, "calls_ok": calls, "calls_failed": fails,
                   "stocks": len(out["stocks"]), "divergent_fields": len(out["divergent"])})
    json.dump(status, open("data/derived/_xval_status.json", "w"), ensure_ascii=False, indent=1)
    print("DONE", status)


if __name__ == "__main__":
    main()
