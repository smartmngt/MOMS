# app.py — moms 진입점 (백그라운드 스캔 + /tmp 공유 상태)
# 잡 상태를 /tmp 파일에 저장 → gunicorn 워커가 여러 개여도 어느 워커든 같은 상태를 응답.
# 권장 실행(더 확실): gunicorn --workers 1 --threads 8 --timeout 120 app:app

import json
import os
import threading
import time
import uuid
import datetime as dt

from flask import Flask, request, jsonify, render_template

from nja.scanner_daily import scan_daily, get_universe

app = Flask(__name__)

JOB_FILE = "/tmp/moms_job.json"
_LOCK = threading.Lock()


def _now():
    return time.time()


def _write(job):
    job = dict(job)
    job["updated_at"] = _now()
    tmp = JOB_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f)
    os.replace(tmp, JOB_FILE)


def _read():
    try:
        with open(JOB_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _idle():
    return {"id": None, "running": False, "done": 0, "total": 0, "found": 0,
            "results": [], "error": None, "started_at": None, "finished_at": None,
            "params": {}, "updated_at": _now()}


def _run_scan(job_id, params):
    state = {"id": job_id, "running": True, "done": 0, "total": 0, "found": 0,
             "results": [], "error": None,
             "started_at": dt.datetime.now().isoformat(timespec="seconds"),
             "finished_at": None, "params": params}

    def progress(done, total, found):
        state["done"], state["total"], state["found"] = done, total, found
        with _LOCK:
            cur = _read()
            if cur and cur.get("id") not in (job_id, None):
                return  # 새 잡이 시작됨 → 이 잡은 더 이상 파일에 쓰지 않음
            _write(state)

    try:
        events = scan_daily(
            params["start"], params["end"],
            surge_min_pct=params["surge_min_pct"],
            turnover_abs_min_eok=params["turnover_abs_min_eok"],
            turnover_mult_min=params["turnover_mult_min"],
            limit=params["limit"],
            progress_cb=progress,
        )
        state["results"] = events
        state["found"] = len(events)
        state["running"] = False
        state["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        state["error"] = str(e)
        state["running"] = False
        state["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")

    with _LOCK:
        cur = _read()
        if not cur or cur.get("id") in (job_id, None):
            _write(state)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    with _LOCK:
        cur = _read()
        # 이미 살아있는(최근 60초 내 갱신된) 잡이 있으면 거부
        if cur and cur.get("running") and (_now() - cur.get("updated_at", 0) < 60):
            return jsonify({"ok": False, "error": "이미 스캔이 돌고 있어요.",
                            "job_id": cur.get("id")}), 409
        data = request.get_json(silent=True) or {}

        def fnum(k, d):
            try:
                return float(data.get(k, d))
            except Exception:
                return d

        start = str(data.get("start", "")).replace("-", "").strip()
        end = str(data.get("end", "")).replace("-", "").strip()
        if len(start) != 8 or len(end) != 8:
            return jsonify({"ok": False, "error": "날짜는 YYYYMMDD 또는 YYYY-MM-DD."}), 400

        params = {"start": start, "end": end,
                  "limit": (int(data.get("limit") or 0) or None),
                  "surge_min_pct": fnum("surge_min_pct", 15.0),
                  "turnover_abs_min_eok": fnum("turnover_abs_min_eok", 200.0),
                  "turnover_mult_min": fnum("turnover_mult_min", 3.0)}
        job_id = uuid.uuid4().hex[:8]
        _write({"id": job_id, "running": True, "done": 0, "total": 0, "found": 0,
                "results": [], "error": None,
                "started_at": dt.datetime.now().isoformat(timespec="seconds"),
                "finished_at": None, "params": params})

    threading.Thread(target=_run_scan, args=(job_id, params), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/status")
def api_status():
    cur = _read() or _idle()
    cur = dict(cur)
    cur["server_now"] = _now()
    if cur.get("running"):
        cur["results"] = []  # 도는 중엔 결과 미전송(가벼움)
    return jsonify(cur)


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
        return jsonify({"code_version": "v6-persist", "listing_count": listing_count,
                        "universe_head": full[:5], "samples": samples})
    except Exception as e:
        return jsonify({"code_version": "v6-persist", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
