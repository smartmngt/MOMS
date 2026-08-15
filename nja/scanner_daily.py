"""
1단계: 일봉 이벤트 스캐너.
전체 유니버스(KOSPI+KOSDAQ)에서 '급등 선발주' 이벤트(종목, 날짜)를 추출한다.
이 결과가 2단계(15분봉 정밀 시뮬)의 입력이 된다.

데이터 소스: pykrx (일봉). 네트워크 되는 환경에서 실행.
이 파일은 뼈대 — 실제 pykrx 호출부는 fetch_* 함수에 채운다.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from .config import NjaConfig, DEFAULT


@dataclass
class SurgeEvent:
    ticker: str
    name: str
    surge_date: str        # 급등(기준봉)일 YYYYMMDD
    surge_pct: float
    turnover: float        # 당일 거래대금
    turnover_mult: float   # 20일평균 대비 배수
    is_leader: bool        # 선발주 여부
    theme: Optional[str] = None


# ── 데이터 취득 (실행 환경에서 pykrx로 구현) ─────────────────────
def fetch_ohlcv_all(start: str, end: str) -> dict:
    """
    유니버스 전 종목의 일봉 OHLCV+거래대금을 {ticker: DataFrame}로.
    TODO(실행환경): pykrx.stock.get_market_ohlcv 등으로 구현.
    각 DataFrame index=날짜, columns=[open,high,low,close,volume,value(거래대금)]
    """
    raise NotImplementedError("pykrx 연동 필요 — 실행 환경에서 구현")


def fetch_ticker_names() -> dict:
    """{ticker: 종목명}. TODO(실행환경): pykrx.stock.get_market_ticker_name"""
    raise NotImplementedError("pykrx 연동 필요")


def fetch_theme_map() -> dict:
    """{ticker: 테마명}. 선발주 판정용. 없으면 빈 dict 반환하고 프록시 사용."""
    return {}


# ── 핵심 스캔 로직 ──────────────────────────────────────────────
def is_surge_bar(row: pd.Series, prev20_avg_value: float, cfg: NjaConfig) -> bool:
    """하루 봉이 '기준봉(급등)' 조건을 만족하는지."""
    pct = row["change_pct"]
    val = row["value"]
    if cfg.use_upper_limit_only:
        if pct < 28.0:            # 상한가 근사
            return False
    else:
        if pct < cfg.surge_min_pct:
            return False
    if val < cfg.turnover_abs_min:
        return False
    if prev20_avg_value > 0 and (val / prev20_avg_value) < cfg.turnover_mult_min:
        return False
    if not (cfg.price_min <= row["close"] <= cfg.price_max):
        return False
    return True


def judge_leader(ticker, surge_dt, theme_map, recent_surges_by_theme, cfg: NjaConfig) -> bool:
    """
    선발주 판정. 테마맵 있으면 '최근 lookback 내 같은 테마 상한가 개수'로,
    없으면 프록시로 근사. 뼈대: 테마맵 경로만 우선, 프록시는 이후 보강.
    """
    if not cfg.use_theme_map or not theme_map:
        return True  # 프록시 미구현 시 일단 통과 (2단계 눌림반등 유무로 자연 필터)
    theme = theme_map.get(ticker)
    if theme is None:
        return True
    prior = recent_surges_by_theme.get(theme, 0)
    return prior < cfg.leader_max_prior_surges


def scan(start: str, end: str, cfg: NjaConfig = DEFAULT) -> list:
    """메인 엔트리. 기간 내 모든 급등 선발주 이벤트를 리스트로 반환."""
    ohlcv = fetch_ohlcv_all(start, end)
    names = fetch_ticker_names()
    theme_map = fetch_theme_map() if cfg.use_theme_map else {}

    events = []
    for ticker, df in ohlcv.items():
        if df is None or len(df) < 25:
            continue
        df = df.copy()
        df["change_pct"] = df["close"].pct_change() * 100
        df["val_ma20"] = df["value"].rolling(20).mean().shift(1)

        for dt, row in df.iterrows():
            if pd.isna(row["change_pct"]) or pd.isna(row["val_ma20"]):
                continue
            if not is_surge_bar(row, row["val_ma20"], cfg):
                continue
            if not judge_leader(ticker, dt, theme_map, {}, cfg):
                continue
            events.append(SurgeEvent(
                ticker=ticker,
                name=names.get(ticker, ticker),
                surge_date=dt.strftime("%Y%m%d") if hasattr(dt, "strftime") else str(dt),
                surge_pct=round(float(row["change_pct"]), 2),
                turnover=float(row["value"]),
                turnover_mult=round(float(row["value"] / row["val_ma20"]), 2),
                is_leader=True,
                theme=theme_map.get(ticker),
            ))
    return events
