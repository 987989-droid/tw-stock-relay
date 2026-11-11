"""公開文件下載（手動觸發專用，2026/11/11 建、11/12 擴充財報）。

用法：
  python scripts/fetch_doc.py str <檔名不含副檔名>            例 336320260902M001（MOPS 法說簡報）
  python scripts/fetch_doc.py fin <代號> <期別,期別,...>      例 3363 202603,202601,202504
      期別＝西元年＋兩位季別（202603＝115Q3；202504＝114 年報）。抓合併財報（AI1）。

輸出：data/docs/<名稱>.txt（pdftotext -layout）。法說簡報另留 PDF（圖片頁要轉圖看）；
      財報只在文字層過少（疑為掃描檔）時才留 PDF。
紀律：失敗即停、不重試。
"""
import os, re, subprocess, sys, time, urllib.parse, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
OUT = "data/docs"


def http(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


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
            if n > 20000:
                os.remove(pdf)          # 有文字層：只留文字版
            else:
                print(fn, "文字層過少，疑為掃描檔，保留 PDF")
        except Exception as e:
            print(fn, "ERR", e); ok = False
        time.sleep(3)
    return ok


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    kind = sys.argv[1]
    if kind == "str":
        r = do_str(sys.argv[2])
    elif kind == "fin":
        r = do_fin(sys.argv[2], [x.strip() for x in sys.argv[3].split(",") if x.strip()])
    else:
        print("未知類型", kind); r = False
    sys.exit(0 if r else 1)
