"""
1단계: 일봉 이벤트 스캐너 (pykrx 연동 완성판).
전체 유니버스(KOSPI+KOSDAQ)에서 '급등 선발주' 이벤트(종목, 날짜)를 추출한다.

성능: 날짜별 전체시세(get_market_ohlcv)를 하루씩 받아 누적 ->
      종목별 시계열로 재구성 -> 급등 조건 판정.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import time
import pandas as pd

from .config import NjaConfig, DEFAULT

try:
    from pykrx import stock
    _HAS_PYKRX = True
except Exception:
    _HAS_PYKRX = False


@dataclass
class SurgeEvent:
    ticker: str
    name: str
    surge_date: str
    surge_pct: float
    turnover: float
    turnover_mult: float
    is_leader: bool
    theme: Optional[str] = None


def _trading_days(start: str, end: str) -> list:
    df = stock.get_index_ohlcv(start, end, "1001")
    return [d.strftime("%Y%m%d") for d in df.index]


def _ohlcv_by_day(date: str, market: str) -> pd.DataFrame:
    df = stock.get_market_ohlcv(date, market=market)
    ren = {"\uc2dc\uac00": "open", "\uace0\uac00": "high", "\uc800\uac00": "low",
           "\uc885\uac00": "close", "\uac70\ub798\ub7c9": "volume",
           "\uac70\ub798\ub300\uae08": "value", "\ub4f1\ub77d\ub960": "change_pct"}
    return df.rename(columns=ren)


def fetch_names(tickers: list) -> dict:
    return {t: stock.get_market_ticker_name(t) for t in tickers}


def is_surge(close, change_pct, value, val_ma20, cfg: NjaConfig) -> bool:
    if cfg.use_upper_limit_only:
        if change_pct < 28.0:
            return False
    else:
        if change_pct < cfg.surge_min_pct:
            return False
    if value < cfg.turnover_abs_min:
        return False
    if val_ma20 and val_ma20 > 0 and (value / val_ma20) < cfg.turnover_mult_min:
        return False
    if not (cfg.price_min <= close <= cfg.price_max):
        return False
    return True


def scan(start: str, end: str, cfg: NjaConfig = DEFAULT) -> list:
    if not _HAS_PYKRX:
        raise NotImplementedError("pykrx \ubbf8\uc124\uce58 - requirements.txt \ud655\uc778")

    warmup_start = _shift_days(start, -40)
    days = _trading_days(warmup_start, end)
    if not days:
        return []

    frames = []
    for d in days:
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                df = _ohlcv_by_day(d, mkt)
                if df is not None and not df.empty:
                    df = df.assign(date=d)
                    frames.append(df)
            except Exception:
                pass
        time.sleep(0.15)

    if not frames:
        return []

    alldf = pd.concat(frames)
    alldf.index.name = "ticker"
    alldf = alldf.reset_index()

    events = []
    names_cache = {}

    for ticker, g in alldf.groupby("ticker"):
        g = g.sort_values("date")
        if len(g) < 21:
            continue
        g = g.copy()
        g["val_ma20"] = g["value"].rolling(20).mean().shift(1)

        for _, row in g.iterrows():
            d = row["date"]
            if d < start:
                continue
            if pd.isna(row["val_ma20"]):
                continue
            if not is_surge(row["close"], row["change_pct"], row["value"],
                            row["val_ma20"], cfg):
                continue
            if ticker not in names_cache:
                try:
                    names_cache[ticker] = stock.get_market_ticker_name(ticker)
                except Exception:
                    names_cache[ticker] = ticker
            events.append(SurgeEvent(
                ticker=ticker,
                name=names_cache[ticker],
                surge_date=d,
                surge_pct=round(float(row["change_pct"]), 2),
                turnover=float(row["value"]),
                turnover_mult=round(float(row["value"] / row["val_ma20"]), 2),
                is_leader=True,
                theme=None,
            ))

    events.sort(key=lambda e: (e.surge_date, -e.turnover))
    return events


def _shift_days(yyyymmdd: str, delta: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(yyyymmdd, "%Y%m%d") + timedelta(days=delta)).strftime("%Y%m%d")
