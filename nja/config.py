"""
N자형 반등 전략 파라미터.
백테스트를 돌리며 이 값들을 조금씩 바꿔가며 튜닝한다.
모든 '튜닝 포인트'를 한 곳에 모아 두어, 코드를 안 건드리고 값만 바꾸게 한다.
"""

from dataclasses import dataclass, asdict


@dataclass
class NjaConfig:
    # ── 1단계: 일봉 이벤트 스캐너 조건 ───────────────────────────
    # 기준봉(급등) 확정
    surge_min_pct: float = 15.0          # 당일 등락률 하한 (%). 상한가 근처 or 장대양봉
    use_upper_limit_only: bool = False   # True면 상한가(≈29.x%)만 인정
    turnover_abs_min: float = 200e8      # 당일 거래대금 절대 하한 (원). 200억
    turnover_mult_min: float = 3.0       # 20일 평균 거래대금 대비 배수 하한

    # 선발주 필터 (재료 소진된 후발주 제외)
    leader_lookback_days: int = 15
    leader_max_prior_surges: int = 2
    use_theme_map: bool = False          # 테마 매핑 데이터 있으면 True

    # 유동성/가격 필터 (극소형 잡주 제거)
    price_min: float = 1000.0            # 최소 주가
    price_max: float = 500000.0          # 최대 주가

    # ── 2단계: 15분봉 정밀 로직 ─────────────────────────────────
    ref_bar_lookahead_days: int = 1      # 기준 15분봉을 찾는 날 = 상한가 다음날(1)
    ref_bar_turnover_topn: int = 1       # 그날 거래대금 상위 N개 15분봉을 기준봉 후보로
    ma_len: int = 5                      # "5선" = 5봉 이동평균 (15분봉 기준)

    # 갈색선: 기준 15분봉의 시가 / 저가(꼬리)
    entry_touch_tol_pct: float = 0.5     # 갈색선 근접 허용 오차 (%)
    split_ratio: tuple = (1, 2)          # 1차:2차 분할 비중 (갈색선 2개)

    # 목표/손절
    target_mode: str = "wave1_high"      # "wave1_high" | "fixed_pct"
    target_fixed_pct: float = 8.0        # target_mode=fixed_pct 일 때 목표 수익률(%)
    stop_mode: str = "second_line_break" # "second_line_break" | "fixed_pct"
    stop_fixed_pct: float = 1.0          # 손절 -% (근사 -1% 검증용)

    # 보유/청산
    max_hold_days: int = 5               # 무조건 5거래일 내 종료

    # ── 자금/비용 ──────────────────────────────────────────────
    capital_per_trade: float = 500000.0  # 초소액 고정 (원)
    fee_bps: float = 15.0                # 편도 수수료+세금 근사 (bp)
    slippage_bps: float = 10.0           # 슬리피지 (bp)

    def to_dict(self):
        d = asdict(self)
        d["split_ratio"] = list(self.split_ratio)
        return d


DEFAULT = NjaConfig()
