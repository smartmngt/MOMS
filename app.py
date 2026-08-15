"""
N자 반등 백테스트 웹앱 (단독 실행).
로컬:      python app.py         → http://localhost:8080
Cloud Run: gunicorn app:app     → Dockerfile 참고

키움 15분봉 수집은 이 앱이 아니라 collector_kiwoom.py(윈도우)에서 수행.
이 앱은 저장된 data/15min/*.parquet 를 읽어 백테스트만 한다.
"""
from __future__ import annotations
import os
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
        return jsonify({"ok": False, "error": f"일봉 데이터 연동 필요: {e}"}), 501


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    body = request.get_json(force=True) or {}
    cfg = _cfg_from_body(body)
    events = [scanner_daily.SurgeEvent(**e) for e in body.get("events", [])]
    result = backtest.run(events, cfg)
    return jsonify({"ok": True, "result": result.__dict__})


@app.route("/api/status")
def api_status():
    """수집된 15분봉 종목 수 등 상태."""
    tickers = data_min.available_tickers()
    return jsonify({"ok": True, "min15_tickers": len(tickers),
                    "sample": tickers[:10]})


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
