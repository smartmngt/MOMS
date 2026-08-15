"""
핵심 전략 로직 (15분봉 기준).

용어:
- 기준봉  : 상한가 다음날, 거래대금 폭발한 15분봉
- 갈색선  : 기준봉의 시가(line1) / 저가·꼬리(line2) → 매수·손절 기준선
- 5선     : 5봉 이동평균 (빨간선)
- 매수     : 갈색선 부근에서 종가가 5선 위로 올라타는(돌파) 순간
- 목표     : 강한 상승 1파의 고점
- 손절     : 2번째 갈색선(더 낮은 선) 이탈
- 청산     : 5거래일 경과 시 강제
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from .config import NjaConfig


@dataclass
class Lines:
    line1: float      # 갈색선 1 (기준봉 시가) — 위쪽
    line2: float      # 갈색선 2 (기준봉 저가) — 아래쪽 = 손절 기준
    target: float     # 목표 (1파 고점)
    ref_time: str     # 기준봉 시각


@dataclass
class Trade:
    ticker: str
    entries: list      # [(time, price, weight), ...]
    exit_time: Optional[str]
    exit_price: Optional[float]
    exit_reason: Optional[str]   # "target" | "stop" | "timeout"
    ret_pct: Optional[float]


def add_ma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    df = df.copy()
    df["ma5"] = df["close"].rolling(n).mean()
    return df


def find_ref_bar(df_next_day: pd.DataFrame, cfg: NjaConfig):
    """상한가 다음날 15분봉들 중 거래대금 최대 봉을 기준봉으로."""
    if df_next_day is None or df_next_day.empty:
        return None
    if "value" not in df_next_day.columns:
        return None
    return df_next_day.sort_values("value", ascending=False).iloc[0]


def build_lines(ref_bar: pd.Series, wave1_high: float) -> Lines:
    """기준봉으로 갈색선 2개 + 목표선 생성."""
    o = float(ref_bar["open"])
    l = float(ref_bar["low"])
    line1, line2 = max(o, l), min(o, l)   # 위/아래 정렬
    return Lines(line1=line1, line2=line2,
                 target=float(wave1_high), ref_time=str(ref_bar.name))


def crossed_up_ma(prev_close, cur_close, prev_ma, cur_ma) -> bool:
    """5선 상향 돌파(아래→위) 순간인지."""
    if any(pd.isna(x) for x in [prev_close, cur_close, prev_ma, cur_ma]):
        return False
    return (prev_close <= prev_ma) and (cur_close > cur_ma)


def near_line(price: float, line: float, tol_pct: float) -> bool:
    return abs(price - line) / line * 100.0 <= tol_pct


def simulate_event(df15: pd.DataFrame, lines: Lines, cfg: NjaConfig,
                   entry_start_idx: int) -> Trade:
    """한 이벤트의 15분봉 시퀀스를 돌며 매수/청산 판정."""
    entries = []
    weights = cfg.split_ratio
    lines_to_watch = [lines.line1, lines.line2]  # 각 갈색선에서 1·2차
    watched = [False, False]
    exit_time = exit_price = exit_reason = None

    rows = df15.reset_index()
    time_col = rows.columns[0]

    for i in range(max(entry_start_idx, 1), len(rows)):
        prev, cur = rows.iloc[i - 1], rows.iloc[i]

        # ── 매수 감시: 갈색선 부근 + 5선 상향돌파 ──
        for k, line in enumerate(lines_to_watch):
            if watched[k]:
                continue
            if near_line(cur["close"], line, cfg.entry_touch_tol_pct) and \
               crossed_up_ma(prev["close"], cur["close"], prev["ma5"], cur["ma5"]):
                entries.append((str(cur[time_col]), float(cur["close"]),
                                weights[k] if k < len(weights) else 1))
                watched[k] = True

        # ── 포지션 있으면 청산 감시 ──
        if entries:
            if cur["high"] >= lines.target:      # 목표 도달
                exit_time, exit_price, exit_reason = str(cur[time_col]), lines.target, "target"
                break
            if cur["close"] < lines.line2:       # 손절: 2번째 갈색선 이탈
                exit_time, exit_price, exit_reason = str(cur[time_col]), float(cur["close"]), "stop"
                break

    # 타임아웃 (기간 끝까지 미청산)
    if entries and exit_reason is None:
        last = rows.iloc[-1]
        exit_time, exit_price, exit_reason = str(last[time_col]), float(last["close"]), "timeout"

    ret_pct = _weighted_return(entries, exit_price, cfg) if entries and exit_price else None

    return Trade(ticker="", entries=entries, exit_time=exit_time,
                 exit_price=exit_price, exit_reason=exit_reason, ret_pct=ret_pct)


def _weighted_return(entries, exit_price, cfg: NjaConfig) -> float:
    """분할매수 가중평균 진입가 대비 수익률(%). 수수료·슬리피지 반영."""
    tot_w = sum(w for _, _, w in entries)
    avg_entry = sum(p * w for _, p, w in entries) / tot_w
    cost = (cfg.fee_bps + cfg.slippage_bps) / 10000.0
    buy = avg_entry * (1 + cost)
    sell = exit_price * (1 - cost)
    return (sell / buy - 1.0) * 100.0
