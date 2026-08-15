"""
키움 15분봉 수집기 (윈도우 PC 전용).

⚠️ 이 스크립트는 Cloud Run에서 안 돈다. 키움 OpenAPI+는 윈도우 COM/OCX 기반.
Jamie의 윈도우 PC(키움 로그인 세션)에서 실행 → data/15min/{ticker}.parquet 저장.
그 parquet를 웹앱(app.py)이 읽어 백테스트한다.

사용 흐름:
  1) 웹앱에서 1단계 스캔 → 이벤트(종목·날짜) 목록 확보 (events.json 저장)
  2) 그 종목들만 이 수집기로 15분봉 저장 (필요 구간만 → 호출 제한 견딤)
  3) 웹앱에서 2단계 백테스트

구현은 TODO: 키움 연동 방식(구 OpenAPI+ / 신 REST)에 맞춰 fetch 함수만 채우면 됨.
"""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

OUT_DIR = Path(__file__).parent / "data" / "15min"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_15min_kiwoom(ticker: str, from_date: str, to_date: str) -> pd.DataFrame:
    """
    TODO(윈도우/키움): opt10080(분봉차트) 15분 조회 구현.
    - tick_range=15
    - 초당 호출 제한 준수 (time.sleep(0.3~) )
    - 반환: index=datetime, columns=[open,high,low,close,volume,value]
    """
    raise NotImplementedError("키움 15분봉 조회 구현 필요 (윈도우 PC)")


def save_ticker(ticker: str, from_date: str, to_date: str):
    df = fetch_15min_kiwoom(ticker, from_date, to_date)
    if df is None or df.empty:
        print(f"[skip] {ticker}: 데이터 없음")
        return
    fp = OUT_DIR / f"{ticker}.parquet"
    if fp.exists():
        old = pd.read_parquet(fp)
        df = pd.concat([old, df]).sort_index()
        df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(fp)
    print(f"[ok] {ticker}: {len(df)} bars -> {fp.name}")


def collect_from_events(events: list, hold_days: int = 5):
    """웹앱 스캔 결과(events)를 받아, 각 이벤트 구간의 15분봉을 수집."""
    from datetime import datetime, timedelta
    for e in events:
        d = datetime.strptime(e["surge_date"], "%Y%m%d")
        frm = d.strftime("%Y%m%d")
        to = (d + timedelta(days=hold_days + 5)).strftime("%Y%m%d")
        try:
            save_ticker(e["ticker"], frm, to)
        except NotImplementedError:
            print("키움 연동 미구현 — fetch_15min_kiwoom 채우세요.")
            break
        time.sleep(0.5)


if __name__ == "__main__":
    import json, sys
    path = sys.argv[1] if len(sys.argv) > 1 else "events.json"
    with open(path, encoding="utf-8") as f:
        events = json.load(f).get("events", [])
    print(f"{len(events)}개 이벤트 수집 시작…")
    collect_from_events(events)
