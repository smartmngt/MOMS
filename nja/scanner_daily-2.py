"""
1단계: 일봉 이벤트 스캐너 (pykrx 연동, 지수 API 미사용 버전).
개장일을 지수 API로 구하지 않고, 날짜를 직접 훑으며 데이터가 있는 날만 사용한다.
(pykrx 버전에 따라 get_index_ohlcv 가 깨지는 문제 회피)
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
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


def _date_range(start: str, end: str) -> list:
    """start~end 사이의 모든 '평일' 날짜 문자열. 실제 개장 여부는 데이터 유무로 판단."""
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    out = []
    d = s
    while d <= e:
        if d.weekday() < 5:  # 월~금만 (주말 제외)
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def _ohlcv_by_day(date: str, market: str) -> pd.DataFrame:
    df = stock.get_market_ohlcv(date, market=market)
    return _normalize_columns(df)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    pykrx 버전마다 컬럼명이 한글/영어로 다를 수 있어, 유연하게 표준화한다.
    표준: open, high, low, close, volume, value, change_pct
    """
    if df is None or df.empty:
        return df
    aliases = {
        "open":  ["\uc2dc\uac00", "open", "Open"],
        "high":  ["\uace0\uac00", "high", "High"],
        "low":   ["\uc800\uac00", "low", "Low"],
        "close": ["\uc885\uac00", "close", "Close"],
        "volume": ["\uac70\ub798\ub7c9", "volume", "Volume"],
        "value": ["\uac70\ub798\ub300\uae08", "value", "Value", "\uac70\ub798\ub300\uae08(\uc6d0)"],
        "change_pct": ["\ub4f1\ub77d\ub960", "change_pct", "\ub4f1\ub77d\ub960(%)", "changes", "change"],
    }
    cols = list(df.columns)
    ren = {}
    for std, names in aliases.items():
        for n in names:
            if n in cols:
                ren[n] = std
                break
    return df.rename(columns=ren)


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
    days = _date_range(warmup_start, end)
    if not days:
        return []

    frames = []
    for d in days:
        got = False
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                df = _ohlcv_by_day(d, mkt)
                if df is not None and not df.empty and df["close"].sum() > 0:
                    frames.append(df.assign(date=d))
                    got = True
            except Exception:
                pass
        if got:
            time.sleep(0.1)  # 개장일에만 잠깐 쉼

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
    return (datetime.strptime(yyyymmdd, "%Y%m%d") + timedelta(days=delta)).strftime("%Y%m%d")
