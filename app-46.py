# app.py — moms 진입점 (백그라운드 스캔 + 상태 폴링)
# ⚠️ gunicorn은 반드시 1 워커여야 함(잡이 메모리에 있음):
#    gunicorn --workers 1 --threads 8 --timeout 120 app:app

import threading
import uuid
import datetime as dt

from flask import Flask, request, jsonify, render_template

from nja.scanner_daily import scan_daily, get_universe

app = Flask(__name__)

JOB = {
    "id": None, "running": False, "done": 0, "total": 0, "found": 0,
    "results": [], "error": None, "started_at": None, "finished_at": None, "params": {},
}
_LOCK = threading.Lock()


def _run_scan(job_id, params):
    def progress(done, total, found):
        with _LOCK:
            if JOB["id"] != job_id:
                return
            JOB["done"], JOB["total"], JOB["found"] = done, total, found
    try:
        events = scan_daily(
            params["start"], params["end"],
            surge_min_pct=params["surge_min_pct"],
            turnover_abs_min_eok=params["turnover_abs_min_eok"],
            turnover_mult_min=params["turnover_mult_min"],
            limit=params["limit"],
            progress_cb=progress,
        )
        with _LOCK:
            if JOB["id"] != job_id:
                return
            JOB["results"], JOB["found"] = events, len(events)
            JOB["running"] = False
            JOB["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        with _LOCK:
            if JOB["id"] != job_id:
                return
            JOB["error"] = str(e)
            JOB["running"] = False
            JOB["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    with _LOCK:
        if JOB["running"]:
            return jsonify({"ok": False, "error": "이미 스캔이 돌고 있어요.", "job_id": JOB["id"]}), 409
        data = request.get_json(silent=True) or {}

        def fnum(key, default):
            try:
                return float(data.get(key, default))
            except Exception:
                return default

        start = str(data.get("start", "")).replace("-", "").strip()
        end = str(data.get("end", "")).replace("-", "").strip()
        if len(start) != 8 or len(end) != 8:
            return jsonify({"ok": False, "error": "날짜는 YYYYMMDD 또는 YYYY-MM-DD."}), 400

        params = {
            "start": start, "end": end,
            "limit": (int(data.get("limit") or 0) or None),
            "surge_min_pct": fnum("surge_min_pct", 15.0),
            "turnover_abs_min_eok": fnum("turnover_abs_min_eok", 200.0),
            "turnover_mult_min": fnum("turnover_mult_min", 3.0),
        }
        job_id = uuid.uuid4().hex[:8]
        JOB.update({
            "id": job_id, "running": True, "done": 0, "total": 0, "found": 0,
            "results": [], "error": None,
            "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "finished_at": None, "params": params,
        })

    threading.Thread(target=_run_scan, args=(job_id, params), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/status")
def api_status():
    with _LOCK:
        return jsonify({
            "id": JOB["id"], "running": JOB["running"],
            "done": JOB["done"], "total": JOB["total"], "found": JOB["found"],
            "error": JOB["error"], "started_at": JOB["started_at"],
            "finished_at": JOB["finished_at"], "params": JOB["params"],
            "results": JOB["results"] if not JOB["running"] else [],
        })


@app.route("/api/diag")
def api_diag():
    try:
        full = get_universe()
        listing_count = len(full)
        samples = []
        import FinanceDataReader as fdr
        for code, name in [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035720", "카카오")]:
            try:
                df = fdr.DataReader(code, "2026-07-01")
                last = df.tail(1)
                samples.append({
                    "code": code, "name": name,
                    "last_date": str(last.index[-1].date()) if len(last) else None,
                    "close": float(last["Close"].iloc[-1]) if len(last) else None,
                })
            except Exception as e:
                samples.append({"code": code, "name": name, "error": str(e)})
        return jsonify({"code_version": "v5-async", "listing_count": listing_count,
                        "universe_head": full[:5], "samples": samples})
    except Exception as e:
        return jsonify({"code_version": "v5-async", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
