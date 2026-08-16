"""
N자 반등 백테스트 웹앱 (단독 실행).
로컬:      python app.py         -> http://localhost:8080
Cloud Run: gunicorn app:app     -> Dockerfile 참고
"""
from __future__ import annotations
import os
import traceback
from flask import Flask, render_template, request, jsonify

from nja.config import NjaConfig, DEFAULT
from nja import scanner_daily, backtest, data_min

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", cfg=DEFAULT.to_dict())


@app.route("/api/scan", methods=["POST"])
def api_scan():
    body = request.get_json(force=True) or {}
    cfg = _cfg_from_body(body)
    start = body.get("start", "20260101")
    end = body.get("end", "20260815")
    try:
        events = scanner_daily.scan(start, end, cfg)
        return jsonify({"ok": True, "count": len(events),
                        "events": [e.__dict__ for e in events]})
    except NotImplementedError as e:
        return jsonify({"ok": False, "error": f"\uc77c\ubd09 \ub370\uc774\ud130 \uc5f0\ub3d9 \ud544\uc694: {e}"}), 501


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    body = request.get_json(force=True) or {}
    cfg = _cfg_from_body(body)
    events = [scanner_daily.SurgeEvent(**e) for e in body.get("events", [])]
    result = backtest.run(events, cfg)
    return jsonify({"ok": True, "result": result.__dict__})


@app.route("/api/status")
def api_status():
    tickers = data_min.available_tickers()
    return jsonify({"ok": True, "min15_tickers": len(tickers),
                    "sample": tickers[:10]})


# ── 진단용: pykrx 가 실제로 데이터를 받는지 확인 ──────────────────
@app.route("/api/diag")
def api_diag():
    """
    ?date=YYYYMMDD  (기본: 20260812)
    그날 KOSPI/KOSDAQ 전체시세를 pykrx로 받아, 몇 종목 왔는지 + 샘플을 반환.
    count 가 0 이면 데이터 수신 실패, 수백~수천이면 정상.
    """
    date = request.args.get("date", "20260812")
    out = {"date": date, "pykrx_installed": scanner_daily._HAS_PYKRX}
    if not scanner_daily._HAS_PYKRX:
        out["error"] = "pykrx not installed"
        return jsonify(out)
    try:
        from pykrx import stock
        result = {}
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                df = scanner_daily._ohlcv_by_day(date, mkt)
                # 거래대금 상위 3개 샘플
                top = []
                if df is not None and not df.empty and "value" in df.columns:
                    t = df.sort_values("value", ascending=False).head(3)
                    for tk, row in t.iterrows():
                        nm = ""
                        try:
                            nm = stock.get_market_ticker_name(tk)
                        except Exception:
                            pass
                        top.append({
                            "ticker": tk, "name": nm,
                            "change_pct": float(row.get("change_pct", 0)),
                            "value_eok": round(float(row.get("value", 0)) / 1e8, 1),
                        })
                result[mkt] = {"count": 0 if df is None else int(len(df)),
                               "top3_by_turnover": top}
            except Exception as e:
                result[mkt] = {"error": f"{type(e).__name__}: {e}"}
        out["result"] = result
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["trace"] = traceback.format_exc()[-1500:]
    return jsonify(out)


def _cfg_from_body(body: dict) -> NjaConfig:
    base = DEFAULT.to_dict()
    over = {k: v for k, v in body.items() if k in base and k != "split_ratio"}
    cfg = NjaConfig(**{**base, **over})
    if isinstance(body.get("split_ratio"), list):
        cfg.split_ratio = tuple(body["split_ratio"])
    return cfg


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
