"""買賣查核用：資料新鮮度檢查（2026/11/12 建）。

用法：python scripts/freshness.py <代號> [YYYY-MM-DD]
只讀中繼既有檔案，不連網、不排程；查核時由 Claude 在 clone 下來的 repo 內執行。
輸出每筆登記資料的「資料日期／保存期限／狀態」。狀態：OK＝可用；STALE＝過期須重抓；MISSING＝中繼沒有。
登記表正本（給人看的）在專案文件「框架/05-台股資訊來源登記表與買賣查核程序」。
"""
import glob, json, os, re, sys
from datetime import date, datetime, timedelta

D = "data"


def roc(s):  # "1151111" 或 "11509" → date（月資料取月底）
    s = str(s)
    if len(s) == 7:
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    y, m = int(s[:3]) + 1911, int(s[3:5])
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def latest_file(pat):
    fs = sorted(glob.glob(pat))
    return fs[-1] if fs else None


def expected_period(today):
    """依法定期限，今天「應該已經有」的最新一期（民國年Q季）。寬限 3 天。"""
    y = today.year - 1911
    t = today - timedelta(days=3)
    marks = [(date(today.year, 3, 31), f"{y-1}Q4"), (date(today.year, 5, 15), f"{y}Q1"),
             (date(today.year, 8, 14), f"{y}Q2"), (date(today.year, 11, 14), f"{y}Q3")]
    exp = f"{y-1}Q3"
    for dl, p in marks:
        if t >= dl:
            exp = p
    return exp


def main():
    co = sys.argv[1]
    today = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    rows = []

    def add(tier, name, gate, data_date, shelf_days, note="", status=None):
        if status is None:
            if data_date is None:
                status = "MISSING"
            else:
                status = "OK" if (today - data_date).days <= shelf_days else "STALE"
        rows.append({"tier": tier, "item": name, "gate": gate, "data_date": str(data_date) if data_date else None,
                     "age_days": (today - data_date).days if data_date else None, "shelf_days": shelf_days,
                     "status": status, "note": note})

    # 市場別
    mkt, close = None, None
    try:
        for r in load(f"{D}/latest/quotes_otc.json"):
            if r.get("SecuritiesCompanyCode") == co:
                mkt, close, qd = "otc", r.get("Close"), roc(r["Date"])
        if not mkt:
            for r in load(f"{D}/latest/quotes_listed.json"):
                if r.get("Code") == co:
                    mkt, close, qd = "listed", r.get("ClosingPrice"), roc(r["Date"])
    except Exception as e:
        print("quotes 讀取失敗", e)
    if not mkt:
        print(f"{co}: 上市與上櫃報價檔都找不到此代號"); sys.exit(1)

    # ── 短 ──
    add("短", "收盤價", "出場②價格閘門", qd, 4, f"收 {close}（{mkt}）")
    for key, nm, gate in (("material", "重大訊息", "閘門①地雷／出場①作廢"), ("insider", "內部人申報轉讓", "閘門①地雷／出場①作廢")):
        f = latest_file(f"{D}/daily/{key}_{mkt}/*.json")
        dd, n = None, 0
        if f:
            dd = date.fromisoformat(os.path.basename(f)[:10])
            for g in sorted(glob.glob(f"{D}/daily/{key}_{mkt}/*.json"))[-30:]:
                try:
                    n += sum(1 for r in load(g) if (r.get("SecuritiesCompanyCode") or r.get("公司代號") or r.get("Code")) == co)
                except Exception:
                    pass
        add("短", nm, gate, dd, 3, f"近 30 個日檔中此代號 {n} 筆")
    f = latest_file(f"{D}/daily/news/*.json")
    add("短", "新聞（指路用，C 級）", "只提示該查哪份原文", date.fromisoformat(os.path.basename(f)[:10]) if f else None, 2)

    # ── 中 ──
    try:
        rh = load(f"{D}/derived/revenue_hist.json").get(co, {})
        ms = sorted(rh.get("months", {}))
        add("中", "月營收", "閘門②月營收驗證", roc(ms[-1]) if ms else None, 45, f"最新 {ms[-1]}，共 {len(ms)} 個月" if ms else "")
    except Exception as e:
        add("中", "月營收", "閘門②月營收驗證", None, 45, f"讀取失敗 {e}")
    f = latest_file(f"{D}/monthly/pledge_{mkt}/*.json")
    add("中", "董監持股與質押", "閘門①地雷／出場①作廢", roc(os.path.basename(f)[:5]) if f else None, 55,
        f"最新 {os.path.basename(f)[:5]}" if f else "")
    docs = sorted(glob.glob(f"{D}/docs/{co}20*M*.txt"))
    add("中", "法說會簡報", "五問②④、產品與地區比重", None, 120,
        ("已存 " + ", ".join(os.path.basename(x)[:-4] for x in docs)) if docs else "中繼沒有；用 fetch_doc（kind=str）手動下載",
        status="OK" if docs else "MISSING")
    try:
        cx = load(f"{D}/derived/hyperscaler_capex.json")
        g = datetime.fromisoformat(cx["generated_at_utc"].replace("Z", "")).date()
        last = cx["calendar_total_ex_orcl"][-1]
        add("中", "大客戶資本支出（美國五家）", "五問④客戶動向、產業需求", g, 9, f"最新季 {last['end']} 合計 YoY {last['yoy_pct']}%")
    except Exception as e:
        add("中", "大客戶資本支出（美國五家）", "五問④客戶動向、產業需求", None, 9, f"讀取失敗 {e}")

    # ── 長 ──
    exp = expected_period(today)
    per = sorted(os.path.basename(p) for p in glob.glob(f"{D}/mops/1*Q*") if glob.glob(f"{p}/{co}_t164sb0*.html"))
    if per:
        n = len(glob.glob(f"{D}/mops/{per[-1]}/{co}_t164sb0*.html"))
        add("長", "季報四大表（MOPS 原文）", "閘門③④⑤", None, 0, f"最新 {per[-1]}（{n}/4 表）；依法定期限應有 {exp}",
            status="OK" if per[-1] >= exp and n == 4 else "STALE")
    else:
        isf = sorted(p for p in glob.glob(f"{D}/derived/is_*.json") if co in load(p))
        add("長", "季報四大表（MOPS 原文）", "閘門③④⑤", None, 0,
            ("僅有損益彙總檔 " + os.path.basename(isf[-1])) if isf else "中繼沒有（非持股清單內）；須另抓",
            status="MISSING")
    fin = sorted(glob.glob(f"{D}/docs/20????_{co}_AI1.txt"))
    if fin:
        p = os.path.basename(fin[-1])[:6]
        rp = f"{int(p[:4]) - 1911}Q{int(p[4:])}"
        add("長", "財報全文與附註", "地區別、帳齡、合約負債、關係人、核閱結論", None, 0, f"最新 {rp}；依法定期限應有 {exp}",
            status="OK" if rp >= exp else "STALE")
    else:
        add("長", "財報全文與附註", "地區別、帳齡、合約負債、關係人、核閱結論", None, 0,
            "中繼沒有；用 fetch_doc（kind=fin）手動下載", status="MISSING")
    add("長", "年報（主要客戶與集中度）", "五問④", None, 0, "未建取得途徑", status="MISSING")
    add("長", "交期與報價", "五問①瓶頸", None, 0, "無公開一手來源，固定為資料不足", status="MISSING")

    print(f"# 新鮮度 {co}（{mkt}） 基準日 {today}")
    for r in rows:
        dd = r["data_date"] or "-"
        print(f"[{r['status']:7}] {r['tier']}｜{r['item']}｜資料日 {dd}｜{r['note']}｜用於：{r['gate']}")
    bad = [r["item"] for r in rows if r["status"] != "OK"]
    print(f"合計 {len(rows)} 項：可用 {len(rows) - len(bad)}、需處理 {len(bad)}（{'、'.join(bad) if bad else '無'}）")


if __name__ == "__main__":
    main()
