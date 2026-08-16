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


# ── 진단용: FinanceDataReader 가 실제로 데이터를 받는지 확인 ──────
@app.route("/api/diag")
def api_diag():
    """
    ?date=YYYYMMDD (기본 20260812)
    - 종목 리스트 로드되는지 (listing_count)
    - 샘플 종목 3개 일봉이 오는지 (samples)
    """
    date = request.args.get("date", "20260812")
    out = {"date": date, "code_version": "v4-fdr",
           "fdr_installed": scanner_daily._HAS_FDR}
    if not scanner_daily._HAS_FDR:
        out["error"] = "FinanceDataReader not installed"
        return jsonify(out)
    try:
        start = scanner_daily._shift_days(date, -10)
        # 1) 종목 리스트
        try:
            listing = scanner_daily._load_listing()
            out["listing_count"] = int(len(listing))
            out["listing_columns"] = list(map(str, listing.columns))
        except Exception as e:
            out["listing_error"] = f"{type(e).__name__}: {e}"
        # 2) 대표 종목 3개 일봉
        samples = {}
        for code, nm in [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035720", "카카오")]:
            try:
                df = scanner_daily._read_daily(code, start, date)
                if df is None or df.empty:
                    samples[code] = {"name": nm, "rows": 0}
                else:
                    last = df.iloc[-1]
                    samples[code] = {
                        "name": nm, "rows": int(len(df)),
                        "last_close": float(last.get("close", 0)),
                        "last_change_pct": round(float(last.get("change_pct", 0)), 2),
                        "columns": list(map(str, df.columns)),
                    }
            except Exception as e:
                samples[code] = {"name": nm, "error": f"{type(e).__name__}: {e}"}
        out["samples"] = samples
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
