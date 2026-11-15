"""公開文件下載（手動觸發專用，2026/11/11 建、11/12 擴充財報）。

用法：
  python scripts/fetch_doc.py str <檔名不含副檔名>            例 336320260902M001（MOPS 法說簡報）
  python scripts/fetch_doc.py fin <代號> <期別,期別,...>      例 3363 202603,202601,202504
      期別＝西元年＋兩位季別（202603＝115Q3；202504＝114 年報）。抓合併財報（AI1）。
  python scripts/fetch_doc.py strlist <代號> [份數]            查 MOPS 法說會一覽，下載最新 N 份簡報（2026/11/15）
  python scripts/fetch_doc.py sec <美股代號> [份數]            EDGAR 最新 N 份 10-Q/10-K/20-F/6-K/40-F（2026/11/15）

輸出：data/docs/<名稱>.txt（pdftotext -layout）。法說簡報另留 PDF（圖片頁要轉圖看）；
      財報只在文字層過少（疑為掃描檔）時才留 PDF。
紀律：失敗即停、不重試。
"""
import os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
OUT = "data/docs"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None   # 自己處理轉址：Python 預設不對 POST 的 307 轉址（2026/11/15 實測法說查詢回 307）


_OPENER = urllib.request.build_opener(_NoRedirect)


def http(url, data=None, hops=4):
    for _ in range(hops):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
        try:
            r = _OPENER.open(req, timeout=120)
            return r.status, r.read()
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                url = urllib.parse.urljoin(url, loc)
                print("  轉址", e.code, "->", url)
                if e.code == 303:
                    data = None
                continue
            raise
    raise RuntimeError("轉址過多")


def to_text(pdf, txt):
    subprocess.run(["pdftotext", "-layout", pdf, txt], check=True)
    return os.path.getsize(txt)


def do_str(name):
    pdf = f"{OUT}/{name}.pdf"
    for host in ("mopsov.twse.com.tw", "mops.twse.com.tw"):
        try:
            s, b = http(f"https://{host}/nas/STR/{name}.pdf")
        except Exception as e:
            print(host, "ERR", e); continue
        print(host, s, len(b))
        if s == 200 and b[:4] == b"%PDF":
            open(pdf, "wb").write(b)
            print("txt bytes", to_text(pdf, f"{OUT}/{name}.txt"))
            return True
    return False


def do_fin(co, periods):
    base = "https://doc.twse.com.tw/server-java/t57sb01"
    ok = True
    for p in periods:
        fn = f"{p}_{co}_AI1.pdf"
        try:
            body = urllib.parse.urlencode({"step": "9", "kind": "A", "co_id": co, "filename": fn}).encode()
            s, b = http(base, body)
            html = b.decode("big5", "replace")
            m = re.search(r"href='(/pdf/[^']+\.pdf)'", html) or re.search(r'href="(/pdf/[^"]+\.pdf)"', html)
            if not m:
                print(fn, "step9", s, "無下載連結；回應前 300 字：", re.sub(r"\s+", " ", html)[:300]); ok = False; continue
            time.sleep(2)
            s, b = http("https://doc.twse.com.tw" + m.group(1))
            if s != 200 or b[:4] != b"%PDF":
                print(fn, "pdf", s, len(b), "非 PDF"); ok = False; continue
            pdf = f"{OUT}/{p}_{co}_AI1.pdf"; txt = pdf[:-4] + ".txt"
            open(pdf, "wb").write(b)
            n = to_text(pdf, txt)
            pages = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
            pg = re.search(r"Pages:\s+(\d+)", pages)
            print(fn, "pdf bytes", len(b), "pages", pg.group(1) if pg else "?", "txt bytes", n)
            # 核閱／查核報告頁多為掃描圖，文字版讀不到：第 3～6 頁另存小圖
            subprocess.run(["pdftoppm", "-r", "70", "-f", "3", "-l", "6", "-png", pdf, pdf[:-4] + "_p"], check=False)
            if n > 20000:
                os.remove(pdf)          # 有文字層：只留文字版
            else:
                print(fn, "文字層過少，疑為掃描檔，保留 PDF")
        except Exception as e:
            print(fn, "ERR", e); ok = False
        time.sleep(3)
    return ok


STR_RE = re.compile(r"(\d{4,6}(20\d{6})M\d{3})")


def do_strlist(co, n_text):
    """代號 → MOPS 法人說明會一覽（ajax_t100sb02_1）→ 列出全部簡報檔名 → 下載最新 n 份。
    2026/11/15 建。year／month 留空＝最新資料；上市（sii）不中再試上櫃（otc）。"""
    n = int(n_text) if (n_text or "").strip().isdigit() else 1
    found, log = {}, []
    roc = time.gmtime().tm_year - 1911
    # 年度留空時 MOPS 回條件頁（2026/11/15 實測 2574 bytes、零命中）→ 改帶民國年，今年、去年各查一次並合併
    for typek in ("sii", "otc"):
        for year in (str(roc), str(roc - 1)):
            body = urllib.parse.urlencode({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                                           "TYPEK": typek, "co_id": co, "year": year, "month": ""}).encode()
            try:
                s, b = http("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1", body)
            except Exception as e:
                log.append(f"{typek} {year} ERR {e}"); continue
            html = b.decode("utf-8", "replace")
            hits = {m.group(1): m.group(2) for m in STR_RE.finditer(html) if m.group(1).startswith(co)}
            head = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:160]
            log.append(f"{typek} {year} http={s} bytes={len(html)} hits={len(hits)} 回應頭：{head}")
            found.update(hits)
            time.sleep(2)
        if found:
            break
    for line in log:
        print(line)
    with open(f"{OUT}/strlist_{co}.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(f"{d} {fn}" for fn, d in sorted(found.items(), key=lambda x: x[1], reverse=True)) + "\n")
    if not found:
        print(co, "查無法說簡報檔名"); return False
    latest = sorted(found.items(), key=lambda x: x[1], reverse=True)[:n]
    print("清單", len(found), "份；下載最新", [x[0] for x in latest])
    ok = True
    for fn, _ in latest:
        ok = do_str(fn) and ok
        time.sleep(3)
    return ok


SEC_UA = "tw-stock-relay research-bot@example.com"   # SEC 要求信箱格式，無則 403（capex.py 2026/11/11 實測）
SEC_FORMS = ("10-Q", "10-K", "20-F", "6-K", "40-F")


def sec_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def do_sec(ticker, n_text):
    """美股代號 → EDGAR 最新 n 份 10-Q/10-K/20-F/6-K/40-F 主文件 → 文字檔（2026/11/15 建）。
    用途：個股結論的美國可比同業對照（第十五節）。"""
    import json, html as htmlmod
    n = int(n_text) if (n_text or "").strip().isdigit() else 1
    t = ticker.upper()
    s, b = sec_get("https://www.sec.gov/files/company_tickers.json")
    print("company_tickers", s, len(b))
    cik = next((v["cik_str"] for v in json.loads(b).values() if v["ticker"].upper() == t), None)
    if cik is None:
        print(t, "查無 CIK"); return False
    time.sleep(1)
    s, b = sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    rec = json.loads(b)["filings"]["recent"]
    rows = [(rec["filingDate"][i], rec["form"][i], rec["accessionNumber"][i], rec["primaryDocument"][i])
            for i in range(len(rec["form"])) if rec["form"][i] in SEC_FORMS]
    print(t, "CIK", cik, "符合表單", len(rows))
    ok = bool(rows)
    for d, form, acc, doc in rows[:n]:
        time.sleep(1)
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
        try:
            s, b = sec_get(url)
            txt = b.decode("utf-8", "replace")
            if doc.lower().endswith((".htm", ".html")):
                txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", txt)
                txt = htmlmod.unescape(re.sub(r"<[^>]+>", " ", txt))
                txt = re.sub(r"[ \t\xa0]+", " ", txt)
                txt = re.sub(r"\n\s*\n+", "\n", txt)
            out = f"{OUT}/sec_{t}_{form}_{d}.txt"
            open(out, "w", encoding="utf-8").write(f"source: {url}\n" + txt)
            print(form, d, "bytes", len(txt), "->", out)
        except Exception as e:
            print(form, d, "ERR", e); ok = False
    return ok


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    kind = sys.argv[1]
    arg3 = sys.argv[3] if len(sys.argv) > 3 else ""
    if kind == "str":
        r = do_str(sys.argv[2])
    elif kind == "fin":
        r = do_fin(sys.argv[2], [x.strip() for x in arg3.split(",") if x.strip()])
    elif kind == "strlist":
        r = do_strlist(sys.argv[2], arg3)
    elif kind == "sec":
        r = do_sec(sys.argv[2], arg3)
    else:
        print("未知類型", kind); r = False
    sys.exit(0 if r else 1)
