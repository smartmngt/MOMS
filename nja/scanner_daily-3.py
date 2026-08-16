"""
1단계: 일봉 이벤트 스캐너 (FinanceDataReader 버전).
pykrx 의 get_market_ohlcv 가 KRX 응답 변경으로 깨지는 문제를 피하기 위해
데이터 소스를 FinanceDataReader(FDR)로 교체.

FDR 특징:
- fdr.StockListing('KRX') : 전체 상장종목 (Code, Name, Market ...)
- fdr.DataReader(code, start, end) : 일봉 (Open High Low Close Volume, 영어컬럼)
- 거래대금 컬럼이 없어 Close*Volume 으로 근사(원 단위)
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from .config import NjaConfig, DEFAULT

try:
    import FinanceDataReader as fdr
    _HAS_FDR = True
except Exception:
    _HAS_FDR = False

# 하위호환: app.py 등에서 _HAS_PYKRX 를 참조하므로 별칭 유지
_HAS_PYKRX = _HAS_FDR


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


# ── 종목 목록 (코드->이름) ─────────────────────────────────────
_LISTING_CACHE = {"df": None}

def _load_listing() -> pd.DataFrame:
    if _LISTING_CACHE["df"] is None:
        df = fdr.StockListing("KRX")
        # 컬럼명이 버전에 따라 다를 수 있어 표준화
        cols = {c.lower(): c for c in df.columns}
        code_col = cols.get("code") or cols.get("symbol") or "Code"
        name_col = cols.get("name") or "Name"
        df = df.rename(columns={code_col: "Code", name_col: "Name"})
        _LISTING_CACHE["df"] = df[["Code", "Name"]].dropna()
    return _LISTING_CACHE["df"]


def _read_daily(code: str, start: str, end: str) -> pd.DataFrame:
    """개별 종목 일봉. index=날짜, columns 표준화(open/high/low/close/volume)."""
    df = fdr.DataReader(code, start, end)
    if df is None or df.empty:
        return None
    ren = {"Open": "open", "High": "high", "Low": "low",
           "Close": "close", "Volume": "volume"}
    df = df.rename(columns=ren)
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    df["value"] = df["close"] * df["volume"]          # 거래대금 근사(원)
    df["change_pct"] = df["close"].pct_change() * 100
    return df


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


def scan(start: str, end: str, cfg: NjaConfig = DEFAULT, limit_codes: int = None) -> list:
    """
    기간 내 급등 이벤트 스캔.
    limit_codes: 개발/테스트용으로 앞 N개 종목만 훑을 때 지정(None이면 전체).
    20일 이동평균 워밍업 위해 시작일을 40일 앞당겨 받는다.
    """
    if not _HAS_FDR:
        raise NotImplementedError("FinanceDataReader \ubbf8\uc124\uce58 - requirements.txt \ud655\uc778")

    listing = _load_listing()
    codes = list(listing["Code"])
    names = dict(zip(listing["Code"], listing["Name"]))
    if limit_codes:
        codes = codes[:limit_codes]

    warmup_start = _shift_days(start, -60)  # 달력일 60일 ≈ 거래일 40일 확보
    events = []

    for code in codes:
        try:
            df = _read_daily(code, warmup_start, end)
        except Exception:
            continue
        if df is None or len(df) < 21:
            continue
        df = df.copy()
        df["val_ma20"] = df["value"].rolling(20).mean().shift(1)

        for dt, row in df.iterrows():
            d = dt.strftime("%Y%m%d") if hasattr(dt, "strftime") else str(dt)
            if d < start:
                continue
            if pd.isna(row.get("val_ma20")) or pd.isna(row.get("change_pct")):
                continue
            if not is_surge(row["close"], row["change_pct"], row["value"],
                            row["val_ma20"], cfg):
                continue
            events.append(SurgeEvent(
                ticker=code,
                name=names.get(code, code),
                surge_date=d,
                surge_pct=round(float(row["change_pct"]), 2),
                turnover=float(row["value"]),
                turnover_mult=round(float(row["value"] / row["val_ma20"]), 2)
                               if row["val_ma20"] else 0.0,
                is_leader=True,
                theme=None,
            ))

    events.sort(key=lambda e: (e.surge_date, -e.turnover))
    return events


def _shift_days(yyyymmdd: str, delta: int) -> str:
    return (datetime.strptime(yyyymmdd, "%Y%m%d") + timedelta(days=delta)).strftime("%Y%m%d")


# 진단/하위호환용: app.py 가 _normalize_columns 를 참조해도 깨지지 않게 유지
def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True):
        return df
    ren = {"Open": "open", "High": "high", "Low": "low",
           "Close": "close", "Volume": "volume"}
    return df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
