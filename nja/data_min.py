"""
15분봉 데이터 로더 (읽기 전용).

키움 API는 윈도우 전용이라 Cloud Run에서 못 돈다.
따라서 수집은 별도(collector_kiwoom.py, 윈도우 PC에서 실행)에서 하고,
여기서는 저장된 parquet 파일을 읽기만 한다 → 로컬/Cloud Run 모두 동작.

파일 규칙: data/15min/{ticker}.parquet
  index=datetime, columns=[open,high,low,close,volume,value]
"""

from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import os
import pandas as pd

# 데이터 위치: 환경변수로 덮어쓸 수 있게 (Cloud Run에서 GCS 마운트 등)
DATA_DIR = Path(os.environ.get("NJA_DATA_DIR", Path(__file__).parent.parent / "data"))
MIN_DIR = DATA_DIR / "15min"


def get_15min(ticker: str, start: str, end: str):
    """
    저장된 15분봉 parquet에서 [start, end] 구간만 잘라 반환.
    파일 없으면 None.
    """
    fp = MIN_DIR / f"{ticker}.parquet"
    if not fp.exists():
        return None
    df = pd.read_parquet(fp)
    if df.empty:
        return None
    idx = pd.to_datetime(df.index)
    s = pd.to_datetime(start, format="%Y%m%d")
    e = pd.to_datetime(end, format="%Y%m%d") + timedelta(days=1)
    return df.loc[(idx >= s) & (idx < e)]


def window_around_event(surge_date: str, hold_days: int):
    """이벤트 기준 필요한 날짜창 (달력일 근사)."""
    d = datetime.strptime(surge_date, "%Y%m%d")
    return d.strftime("%Y%m%d"), (d + timedelta(days=hold_days + 5)).strftime("%Y%m%d")


def available_tickers() -> list:
    """수집된 15분봉이 있는 종목 코드 목록."""
    if not MIN_DIR.exists():
        return []
    return sorted(p.stem for p in MIN_DIR.glob("*.parquet"))
