#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_news.py — 在 fetch_news.py 之後執行，替當日新聞加上兩個機械標記欄位。

為什麼要有這一支：
  讀取端（Cowork 排程）原本只能用 c 欄（文中「(2330)」式數字股號）比對。
  2026-09-07 實測：當日 157 則新聞中只有 19 則帶數字股號，其餘 138 則
  必須靠讀取端「人工判讀標題是否觸及論點變數」——無人值守時品質會浮動。
  同日實測人工掃 138 則只撈出 3 則，而機械關鍵詞比對撈出 14 則，
  其中 4 則是人工漏掉的（矽光子聯盟、載板告急、CCL、AI光通訊）。
  結論：機械比對的價值不在取代判斷，而在**把候選從 138 則壓到約 14 則**，
  讓讀取端只需判讀少量候選，而不是掃過全部標題。

【隱私鐵則 — 本 repo 為公開 repo】
  本檔**不得包含任何持股／追蹤清單股號，也不得包含任何可反推持股的對應關係**。
  TOPIC_KW 只放「產業主題詞」，涵蓋整條 AI 硬體供應鏈，看不出誰持有什麼。
  「哪個主題對應哪一檔」一律由讀取端用自己保管的清單去對，永不寫進本 repo。

新增欄位（皆為附加，不改動既有欄位）：
  cn  : 由公司「名稱」比對出的代號（中信心）。與 c（數字擷取，高信心）分開放，
        讓讀取端能分級處理。名稱對照表直接由 repo 內既有的月營收檔建立，不另外抓取。
  kwt : 命中的產業主題詞清單。這是「丙條件」的機械化。

設計原則：寧可多標、不可漏標。誤標由讀取端過濾，漏標則永遠救不回來。
"""
import json, os, glob, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 名稱比對的排除清單 ──────────────────────────────────────────
# 這些公司簡稱同時是常用詞或人名，直接比對會大量誤命中。
# 已知實例：2026-09-07「拜登兒子杭特可能參選 2028」被比對成 杭特(3297)。
NAME_STOP = {
    "大同", "統一", "中華", "台灣", "第一", "國際", "中國", "富邦", "元大", "永豐",
    "合庫", "開發", "國票", "日盛", "台名", "力麗", "三洋", "東元", "國建", "南亞",
    "中鋼", "台塑", "杭特", "大成", "勤益", "華新", "遠東", "中興", "亞洲", "全國",
    "新光", "台新", "上海", "聯合", "中信", "王道", "京城", "遠傳", "誠品", "光泉",
}

# ── 產業主題詞（丙條件機械化）────────────────────────────────────
# 純產業詞彙，不含股號、不含持股意涵。刻意放寬涵蓋整條 AI 硬體供應鏈，
# 使日後換股不必改動本 repo。
# 註：使用者 2026/09/07 明確指示「不要收緊」——寧可多給候選，由查證階段篩掉。
TOPIC_KW = [
    # 光通訊 / 矽光子
    "CPO", "矽光子", "矽光", "共同封裝", "光通訊", "光收發", "光引擎", "光模組",
    "MPO", "EML", "矽光電",
    # 封測 / 測試
    "封測", "測試機", "探針", "探針卡", "金凸塊", "COF", "驅動IC", "先進封裝",
    "CoWoS", "SoIC", "扇出", "打線", "覆晶",
    # 記憶體
    "記憶體", "NAND", "DRAM", "HBM", "快閃", "顆粒", "模組廠", "鎧俠", "Kioxia",
    # PCB / 載板 / 材料
    "PCB", "印刷電路", "軟板", "硬板", "軟硬板", "載板", "ABF", "CCL", "銅箔基板",
    "銅箔", "玻纖布", "壓合",
    # 矽智財 / 設計服務
    "矽智財", "IP授權", "ASIC", "設計服務", "IC設計", "委託設計", "EDA",
    # 廠務 / 統包 / 設備
    "廠務", "無塵室", "機電", "統包", "潔淨室", "擴產潮", "資本支出", "設備支出",
    # 重電 / 電網
    "重電", "變壓器", "電網", "台電", "超高壓", "開關設備", "配電", "儲能", "電價",
    # 散熱 / 電源 / 機構
    "散熱", "液冷", "水冷板", "均熱片", "電源供應", "機殼", "機構件",
    # 終端與客戶
    "AI伺服器", "伺服器", "機櫃", "資料中心", "算力", "雲端資本支出",
    "輝達", "NVIDIA", "博通", "超微", "台積電", "鴻海", "緯創", "廣達",
    # 醫材（可成轉型）
    "醫材", "骨科", "醫療器材",
    # 治理 / 財報事件（跨檔通用）
    "內部稽核", "財務主管", "會計主管", "會計師", "財報重編", "保留意見",
    "現金增資", "可轉債", "GDR", "私募", "減資", "庫藏股", "設質", "質押",
]


# ── 大盤行情快訊偵測（nz 旗標）───────────────────────────────
# 2026/09/07 實測：當日 263 則中有 35 則是「台股漲幾點、台積電漲幾元」的
# 指數行情快訊，同一件事被七八家媒體各發一次。這類標題裡的公司名是**報價**，
# 不是產業事件，對任何論點變數都不構成證據。
#
# 設計原則（重要）：**只降級、不刪除**。誤刪永遠救不回來，誤降級只是排序靠後。
# 因此判準要求「指數詞」與「漲跌點數詞」同時出現，缺一不標，寧可漏標。
# 已驗證不會誤標的實例：「CPO 題材已漲 242%」「台光電 CCL 供不應求…目標價 6,000 元」
# 「信驊…優於大盤評等目標價 23,000 元」「費半回檔2成」「輝達收購 Hugging Face」。
NZ_IDX = re.compile(r"台股|大盤|加權|台指|指數|日經|道瓊|那斯達克|費半|標普|恆生")
NZ_MOVE = re.compile(r"開盤|收盤|早盤|盤中|尾盤|盤前|漲逾|跌逾|漲\d|跌\d|\d[\d,]*點|"
                     r"站上|站回|重返|收復|攻克|攻上|大關|\d+K|萬\d")


def is_noise(title):
    """指數行情快訊回 True。僅供讀取端降序處理，不得用於刪除。"""
    return bool(NZ_IDX.search(title) and NZ_MOVE.search(title))


# ── 重大事件偵測（ev 旗標，優先於 nz）─────────────────────────
# 2026/09/07 實測抓到的漏洞：「台股狂飆780點！欣興揮別**洗產地**陰霾上漲逾5%」
# 被 nz 判為行情快訊而降級，但它講的是洗產地監理案——與同日「欣興案衝擊
# 兩岸接力生產恐洗牌」是同一件事，直接觸及 PCB／載板持股的產地結構。
# 教訓：**一則新聞可以同時是行情快訊與實質事件**，只看標題型態會誤降級。
#
# 規則：命中事件詞者 ev=true，且**強制不標 nz**（事件優先於行情）。
# 事件則一律獨立列出並附連結，不併入行情快訊群組。
EVENT_KW = re.compile(
    r"洗產地|原產地|轉單規避|規避關稅|反傾銷|課徵關稅|禁令|制裁|出口管制|實體清單|"
    r"搜索|起訴|偵查|約談|羈押|訴訟|仲裁|專利侵權|求償|"
    r"裁罰|罰鍰|處分金|糾正|函詢|命令改善|限期改善|"
    r"財報重編|重編|更正財報|保留意見|無法表示意見|會計師異動|更換會計師|"
    r"內部稽核|稽核主管|財務主管異動|會計主管異動|"
    r"停止買賣|停牌|變更交易|下市|下櫃|全額交割|違約交割|"
    r"掏空|內線交易|假帳|財報不實|資產凍結|"
    r"火災|爆炸|停工|罷工|斷鏈|召回|資安事件|遭駭|勒索軟體|"
    r"現金增資|可轉債|GDR|私募|減資|設質|質押|申報轉讓")
# 這幾個詞在一般報導裡是中性用語，命中僅這些不算事件
EVENT_FALSE = re.compile(r"調查顯示|問卷調查|民意調查|民調|調查報告|市場調查")


def is_event(title):
    """重大事件回 True。ev 優先於 nz：事件則不得被當成行情快訊降級。"""
    if EVENT_FALSE.search(title):
        return False
    return bool(EVENT_KW.search(title))


def load_name_map():
    """由 repo 內既有的月營收檔建 名稱→代號 對照表（免額外抓取來源）。

    月營收檔本身就含 公司代號 + 公司名稱，涵蓋上市／上櫃／興櫃約 2,300 家，
    每月更新一次即可，公司名稱極少變動。
    """
    m = {}
    for key in ("revenue_listed", "revenue_otc", "revenue_emerging"):
        d = os.path.join(ROOT, "data", "monthly", key)
        if not os.path.isdir(d):
            continue
        files = sorted(glob.glob(os.path.join(d, "*.json")))
        if not files:
            continue
        try:
            with open(files[-1], encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            print("  名稱表讀取失敗 %s: %r" % (key, e))
            continue
        for r in rows:
            c = str(r.get("公司代號", "")).strip()
            n = str(r.get("公司名稱", "")).strip()
            if c and n and len(n) >= 2 and n not in NAME_STOP:
                m.setdefault(n, c)
    return m


def main():
    idx_path = os.path.join(ROOT, "data", "latest.json")
    try:
        with open(idx_path, encoding="utf-8") as f:
            manifest = json.load(f)
        rel = manifest["files"]["news"]["path"]
    except Exception as e:
        print("找不到 news 索引，跳過標記（非致命）:", repr(e))
        return

    news_path = os.path.join(ROOT, rel)
    try:
        with open(news_path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print("讀不到 news 檔，跳過標記（非致命）:", repr(e))
        return

    name_map = load_name_map()
    # 長名優先比對，避免短名先吃掉（例：「聯電」不應搶在「聯電子」之前）
    names = sorted(name_map.keys(), key=len, reverse=True)
    print("名稱對照表:", len(name_map), "家")

    items = payload.get("items", [])
    n_cn = n_kwt = n_nz = n_ev = 0
    for it in items:
        text = (it.get("t") or "") + " " + (it.get("d") or "")
        if not text.strip():
            continue

        existing = set(it.get("c") or [])
        cn = []
        for nm in names:
            if nm in text:
                code = name_map[nm]
                if code not in existing and code not in cn:
                    cn.append(code)
                if len(cn) >= 8:
                    break
        if cn:
            it["cn"] = cn
            n_cn += 1

        kwt = [k for k in TOPIC_KW if k in text]
        if kwt:
            it["kwt"] = kwt[:12]
            n_kwt += 1

        title = it.get("t") or ""
        if is_event(title):
            it["ev"] = True
            n_ev += 1
        elif is_noise(title):
            it["nz"] = True
            n_nz += 1

    # ── 行情快訊去重（只歸類、不刪除）────────────────────────
    # 2026/09/07 使用者指示：「台積電漲30元 台股早盤漲逾600點站上47000點」這類
    # 重複性太高，只出一則，其餘與它相同、不影響判定者歸類為同一則消息。
    # 作法：nz=true 者視為當日同一則大盤行情的不同媒體版本，取 ts 最新者為代表
    # （nzr=true），其餘標 nzdup=true 並記下群組大小。**一則都不刪除。**
    nz_items = [x for x in items if x.get("nz")]
    if nz_items:
        nz_items.sort(key=lambda x: (x.get("ts") or ""), reverse=True)
        nz_items[0]["nzr"] = True
        for x in nz_items[1:]:
            x["nzdup"] = True
    payload["nz_group_size"] = len(nz_items)
    payload["ev_count"] = n_ev
    payload["cn_count"] = n_cn
    payload["kwt_count"] = n_kwt
    payload["nz_count"] = n_nz
    payload["enrich_note"] = (
        "cn＝由公司名稱比對出的代號（中信心，與 c 的數字擷取分開，可能誤命中，"
        "已用 NAME_STOP 排除常用詞與人名）；kwt＝命中的產業主題詞（丙條件機械化，"
        "刻意放寬、寧可多標）。兩者皆為候選標記，非結論；"
        "哪個主題對應哪一檔一律由讀取端自行對照，本 repo 不存任何持股資訊。"
        "nz=true 表示該則為大盤指數行情快訊（報價，非產業事件），"
        "**僅供讀取端降序處理，不得據以刪除或略過**；其中 nzr=true 為該群組代表則，"
        "nzdup=true 為同一則消息的其他媒體版本，讀取端只需顯示代表則並註明另有幾則同型。"
        "ev=true 表示標題命中重大事件詞（監理、訴訟、關稅、財報重編、稽核人事、"
        "停牌、籌資稀釋、質押、天災停工等），**ev 優先於 nz，事件則一律獨立列出並附連結**。"
    )

    with open(news_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    # 同步更新索引裡的統計，讓讀取端不必開檔就知道有沒有這兩欄
    try:
        manifest["files"]["news"]["cn_count"] = n_cn
        manifest["files"]["news"]["kwt_count"] = n_kwt
        manifest["files"]["news"]["nz_count"] = n_nz
        manifest["files"]["news"]["ev_count"] = n_ev
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("併入索引失敗（非致命）:", repr(e))

    total = len(items)
    print("標記完成：共 %d 則｜cn %d｜kwt %d｜nz %d（代表 1 則）｜ev %d" % (
        total, n_cn, n_kwt, n_nz, n_ev))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("enrich_news failed (non-fatal): %r" % e)
        sys.exit(0)
