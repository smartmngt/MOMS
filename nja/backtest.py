"""
백테스트 오케스트레이터.
1단계 이벤트 리스트 → 각 이벤트마다 15분봉 로딩 → 전략 시뮬 → 성과 집계.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
import pandas as pd

from .config import NjaConfig, DEFAULT
from .scanner_daily import SurgeEvent
from . import data_min
from . import strategy_nja as strat


@dataclass
class BacktestResult:
    n_events: int
    n_trades: int
    win_rate: float
    avg_ret: float
    median_ret: float
    sum_ret: float
    payoff: float            # 평균이익/평균손실
    by_reason: dict          # {target: n, stop: n, timeout: n}
    trades: list             # 상세


def _next_trading_day_slice(df15: pd.DataFrame, surge_date: str, lookahead: int):
    """기준봉일 이후 lookahead 거래일째의 15분봉 슬라이스 + 그 이후 전체."""
    if df15 is None or df15.empty:
        return None, None
    df15 = df15.copy()
    df15["_d"] = pd.to_datetime(df15.index).date
    days = sorted(set(df15["_d"]))
    from datetime import datetime
    sdate = datetime.strptime(surge_date, "%Y%m%d").date()
    after = [d for d in days if d > sdate]
    if len(after) < lookahead:
        return None, None
    ref_day = after[lookahead - 1]
    ref_slice = df15[df15["_d"] == ref_day].drop(columns=["_d"])
    rest = df15[df15["_d"] >= ref_day].drop(columns=["_d"])
    return ref_slice, rest


def run(events: list, cfg: NjaConfig = DEFAULT) -> BacktestResult:
    trades = []
    reason_count = {"target": 0, "stop": 0, "timeout": 0}

    for ev in events:
        start, end = data_min.window_around_event(ev.surge_date, cfg.max_hold_days)
        df15 = data_min.get_15min(ev.ticker, start, end)
        if df15 is None or df15.empty:
            continue

        ref_slice, rest = _next_trading_day_slice(df15, ev.surge_date, cfg.ref_bar_lookahead_days)
        if ref_slice is None or rest is None or rest.empty:
            continue

        ref_bar = strat.find_ref_bar(ref_slice, cfg)
        if ref_bar is None:
            continue

        # 강한 상승 1파의 고점 = 구간 내 고점(근사). 실행 시 정교화 가능.
        wave1_high = float(df15["high"].max())

        lines = strat.build_lines(ref_bar, wave1_high)
        rest = strat.add_ma(rest, cfg.ma_len)

        trade = strat.simulate_event(rest, lines, cfg, entry_start_idx=1)
        trade.ticker = ev.ticker
        if not trade.entries:
            continue

        trades.append(trade)
        if trade.exit_reason in reason_count:
            reason_count[trade.exit_reason] += 1

    return _aggregate(len(events), trades, reason_count)


def _aggregate(n_events, trades, reason_count) -> BacktestResult:
    rets = [t.ret_pct for t in trades if t.ret_pct is not None]
    if not rets:
        return BacktestResult(n_events, 0, 0, 0, 0, 0, 0, reason_count, [])
    s = pd.Series(rets)
    wins = s[s > 0]
    losses = s[s <= 0]
    payoff = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else float("inf")
    return BacktestResult(
        n_events=n_events,
        n_trades=len(trades),
        win_rate=round((s > 0).mean() * 100, 2),
        avg_ret=round(s.mean(), 3),
        median_ret=round(s.median(), 3),
        sum_ret=round(s.sum(), 3),
        payoff=round(payoff, 2) if payoff != float("inf") else None,
        by_reason=reason_count,
        trades=[asdict(t) for t in trades],
    )
