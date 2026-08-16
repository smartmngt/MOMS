# nja/scanner_daily.py
# 1단계 일봉 스캐너 (FDR) — 급등 선발주 이벤트 추출
# 병렬 fetch + 진행률 콜백 + 종목수 제한 지원

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import FinanceDataReader as fdr


def get_universe(limit=None):
    """전체 KRX 종목 리스트 [(code, name), ...]. limit 있으면 앞에서 그만큼."""
    listing = fdr.StockListing("KRX")
    cols = list(listing.columns)
    code_col = next((c for c in ["Code", "Symbol", "종목코드"] if c in cols), cols[0])
    name_col = next((c for c in ["Name", "종목명"] if c in cols), cols[1])
    df = listing[[code_col, name_col]].dropna().copy()
    df.columns = ["Code", "Name"]
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df = df[df["Code"].str.fullmatch(r"\d{6}")]
    codes = list(df.itertuples(index=False, name=None))
    if limit:
        codes = codes[:limit]
    return codes


def _fetch_one(code, name, start, end):
    try:
        df = fdr.DataReader(code, start, end)
        if df is None or df.empty:
            return None
        return (code, name, df.dropna())
    except Exception:
        return None


def scan_daily(scan_start, scan_end,
               surge_min_pct=15.0,
               turnover_abs_min_eok=200.0,
               turnover_mult_min=3.0,
               vol_lookback=20,
               limit=None,
               max_workers=16,
               progress_cb=None):
    """
    scan_start, scan_end: 'YYYYMMDD'
    반환: [{date, code, name, change_pct, turnover_eok, turnover_mult}, ...]
    progress_cb(done, total, found) 주기 호출.
    """
    codes = get_universe(limit=limit)
    total = len(codes)

    s = dt.datetime.strptime(scan_start, "%Y%m%d")
    fetch_start = (s - dt.timedelta(days=60)).strftime("%Y-%m-%d")
    fetch_end = dt.datetime.strptime(scan_end, "%Y%m%d").strftime("%Y-%m-%d")
    win_start = pd.Timestamp(scan_start)
    win_end = pd.Timestamp(scan_end)

    events = []
    done = 0

    def handle(df, code, name):
        out = []
        if "Close" not in df.columns or "Volume" not in df.columns:
            return out
        c = df["Close"].astype(float)
        v = df["Volume"].astype(float)
        turnover_eok = (c * v) / 1e8            # 억원 근사 (종가*거래량)
        change = c.pct_change() * 100.0          # 등락률 %
        avg_eok = turnover_eok.rolling(vol_lookback).mean()
        for idx in df.index:
            if idx < win_start or idx > win_end:
                continue
            ch = change.get(idx)
            to = turnover_eok.get(idx)
            if pd.isna(ch) or pd.isna(to):
                continue
            if ch < surge_min_pct or to < turnover_abs_min_eok:
                continue
            avg = avg_eok.get(idx)
            mult = (to / avg) if (avg is not None and not pd.isna(avg) and avg > 0) else None
            if turnover_mult_min and mult is not None and mult < turnover_mult_min:
                continue
            out.append({
                "date": idx.strftime("%Y-%m-%d"),
                "code": code, "name": name,
                "change_pct": round(float(ch), 2),
                "turnover_eok": round(float(to), 1),
                "turnover_mult": round(float(mult), 1) if mult is not None else None,
            })
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_one, code, name, fetch_start, fetch_end): code
                for code, name in codes}
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            if res is not None:
                code, name, df = res
                evs = handle(df, code, name)
                if evs:
                    events.extend(evs)
            if progress_cb and (done % 20 == 0 or done == total):
                progress_cb(done, total, len(events))

    events.sort(key=lambda e: (e["date"], -e["turnover_eok"]))
    return events
