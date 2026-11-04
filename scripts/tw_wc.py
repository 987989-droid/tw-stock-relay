"""台股組裝三家營運資金原料（MOPS 資產負債表＋綜合損益表，最新一季與前一季）。

設計（2026/11/04 改版，起因：同日多次重跑後 MOPS 回 Connection refused）：
1. 快取：已發布的季報不會變，已完整取得的期別直接沿用 repo 內舊檔，不再打 MOPS。
   每家只需 1 次請求確認「最新期別」；只有新期別才抓。
2. 節流：每次請求間隔 4 秒。
3. 退避：連線被拒、逾時或 5xx 時，等 30 秒、60 秒各再試一次（單一請求最多 3 次），
   每次嘗試都記入 status，不靜默。仍失敗 → 該公司標失敗，不湊數。
4. 驗證：回傳頁的 CO_ID／SYEAR／SSEASON 必須與請求一致，否則整筆作廢。
輸出：data/selftest/macro/tw_wc.json、tw_wc_status.json。"""
import json, os, re, time, datetime, urllib.request, urllib.parse, urllib.error

OUT = "data/selftest/macro"
CODES = ["2382", "2317", "3231"]
HOSTS = ["https://mopsov.twse.com.tw/mops/web/ajax_", "https://mops.twse.com.tw/mops/web/ajax_"]  # 第二個為備援，實測結果見 status
WC_KEYS = re.compile(r"應收帳款|應付帳款|^存貨$|營業收入合計")
META = re.compile(r"CO_ID=(\d+)&SYEAR=(\d+)&SSEASON=(\d+)")
GAP, BACKOFF = 4, [30, 60]
log = {"run_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "requests": 0, "attempts": [], "companies": {}}


def mops(table, co, isnew, y="", s=""):
    body = urllib.parse.urlencode({"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "queryName": "co_id",
                                   "inpuType": "co_id", "TYPEK": "all", "isnew": isnew, "co_id": co, "year": y, "season": s}).encode()
    for i in range(len(BACKOFF) + 1):
        for host in HOSTS:  # 每一輪先試主站，被拒再試備援站
            time.sleep(GAP)
            log["requests"] += 1
            tag = "主站" if host == HOSTS[0] else "備援站"
            try:
                req = urllib.request.Request(host + table, data=body, headers={"User-Agent": "Mozilla/5.0",
                                             "Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    h = r.read().decode("utf-8", "replace")
                if i or host != HOSTS[0]:
                    log["attempts"].append(f"{co} {table} {y}Q{s} 第{i + 1}輪{tag}成功")
                return h
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                code = getattr(e, "code", None)
                log["attempts"].append(f"{co} {table} {y}Q{s} 第{i + 1}輪{tag}失敗：{repr(e)[:110]}")
                if code and code < 500 and host == HOSTS[-1]:
                    raise
        if i < len(BACKOFF):
            time.sleep(BACKOFF[i])
    raise ConnectionError(f"{co} {table} {y}Q{s} 三輪主站與備援站皆失敗")


def rows(h):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if cells and (WC_KEYS.search(cells[0]) or cells[0] == "會計項目"):
            out.append(cells[:7])
    return out


def complete(rec):
    return bool(rec) and any(r[0] == "營業收入合計" for r in rec.get("t164sb04", [])) and \
        any(r[0].startswith("應收帳款") for r in rec.get("t164sb03", []))


def check(h, co, yy, qq, t):
    m = META.search(h)
    if not m or m.group(1) != co or int(m.group(2)) - 1911 != yy or int(m.group(3)) != qq:
        raise ValueError(f"{t} {yy}Q{qq} 回傳代號或期別不符（{m.groups() if m else '抽不到'}）")


try:
    cache = json.load(open(f"{OUT}/tw_wc.json"))
except Exception:
    cache = {}

wc = {}
for co in CODES:
    st = {"cached": [], "fetched": []}
    try:
        h = mops("t164sb03", co, "true")
        m = META.search(h)
        if not m or m.group(1) != co:
            raise ValueError("最新期別頁代號或期別抽不到")
        y, q = int(m.group(2)) - 1911, int(m.group(3))
        periods = [(y, q)] + ([(y, q - 1)] if q > 1 else [])  # 跨年度 Q4 為全年報表，不取
        wc[co] = {}
        for (yy, qq) in periods:
            key = f"{yy}Q{qq}"
            old = cache.get(co, {}).get(key)
            if complete(old):
                wc[co][key] = old
                st["cached"].append(key)
                continue
            rec = {}
            for t in ("t164sb03", "t164sb04"):
                hh = h if (t == "t164sb03" and (yy, qq) == (y, q)) else mops(t, co, "false", str(yy), str(qq))
                check(hh, co, yy, qq, t)
                rec[t] = rows(hh)
            if not complete(rec):
                raise ValueError(f"{key} 欄位不全（缺營業收入合計或應收帳款列）")
            wc[co][key] = rec
            st["fetched"].append(key)
        st["result"] = "ok"
    except Exception as e:
        st["result"] = repr(e)[:200]
        # 失敗時保留舊快取中的完整期別，讓計算端自行判斷是否缺期
        kept = {k: v for k, v in cache.get(co, {}).items() if complete(v)}
        kept.update(wc.get(co, {}))  # 本次已成功抓到的期別也保留
        wc[co] = dict(sorted(kept.items(), reverse=True))
        st["kept"] = list(wc[co])
    log["companies"][co] = st

os.makedirs(OUT, exist_ok=True)
json.dump(wc, open(f"{OUT}/tw_wc.json", "w"), ensure_ascii=False, indent=0)
json.dump(log, open(f"{OUT}/tw_wc_status.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(log, ensure_ascii=False))
