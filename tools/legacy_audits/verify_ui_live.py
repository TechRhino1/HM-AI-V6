"""Live end-to-end check of the API surface.

Starts the real HTTP server on a scratch port with no broker attached, then
exercises every route the browser would call.

Usage (from the repo root):

    python tools/verify_ui_live.py

Exit code is 0 when every check passes, 1 otherwise, so it can gate a release.

Two things this script deliberately proves rather than assumes:

* ``/api/action/auto-select`` stays a dry run even when asked to go live. The
  HTTP surface must have no path that can open a trade.
* With no orchestrator attached, auto-selection reports ``UNAVAILABLE`` with a
  reason instead of returning an empty-but-successful selection. Failing safe
  and saying so is the correct behaviour; a 200 with no decisions would let a
  caller mistake "engine not wired" for "nothing to trade".
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

# Run from anywhere: put the repo root on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.api.server import start_server

PORT = 8599
BASE = f"http://127.0.0.1:{PORT}"

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


# Statuses a provider-backed route may legitimately answer. Anything else is a
# failure, including the synthetic status 0 that request() returns when the
# client gives up: a route that never answers pins a server thread, which is
# worse than one that errors.
PROVIDER_OK = (200, 503, 504)


def request(path, payload=None, timeout=60):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (TimeoutError, urllib.error.URLError) as exc:
        # A route that never answers is a result, not a crash. Status 0 is
        # deliberately not a real HTTP code so a caller can tell "hung" apart
        # from "answered 500" — the two need different fixes.
        return 0, json.dumps({"error": f"no response within {timeout}s: {exc}"})


def main():
    server = start_server(host="127.0.0.1", port=PORT, mt5_client=None, orchestrator=None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1.5)

    try:
        # ── 1. Page routing ────────────────────────────────────────────────
        # The UI timeframe selector was inert for a while: it sent
        # `timeframe=` while the handler read `tf=`, so every request silently
        # came back as H1 whatever the user picked. Assert that both spellings
        # are honoured AND that two different timeframes really do return
        # different series — accepting the parameter and then ignoring it would
        # pass a weaker check.
        series = {}
        for label, qs in (
            ("tf", "symbol=XAUUSD&tf=H1"),
            ("timeframe", "symbol=XAUUSD&timeframe=H1"),
            ("M5", "symbol=XAUUSD&tf=M5"),
        ):
            status, body = request("/api/candles?" + qs)
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            candles = payload.get("candles") or []
            series[label] = {
                "status": status,
                "tf": payload.get("timeframe"),
                "n": len(candles),
                "first": candles[0]["time"] if candles else None,
            }

        record(
            "GET /api/candles accepts both tf and timeframe",
            series["tf"]["tf"] == "H1" and series["timeframe"]["tf"] == "H1",
            f"tf={series['tf']['tf']} timeframe={series['timeframe']['tf']}",
        )
        record(
            "GET /api/candles honours the requested timeframe",
            series["M5"]["tf"] == "M5" and series["M5"]["first"] != series["tf"]["first"],
            f"H1 first={series['tf']['first']} M5 first={series['M5']['first']}",
        )

        status, body = request("/api/pending_orders")
        record(
            "GET /api/pending_orders dispatches",
            status in (200, 503),
            f"status={status}",
        )

        # The retired UI must be genuinely gone, not merely unrouted.
        status, _ = request("/static/js/app_shell.js")
        record(
            "retired app_shell.js is no longer served",
            status == 404,
            f"status={status}",
        )

        # ── 3. Intelligence GET endpoints ──────────────────────────────────
        status, body = request("/api/intelligence/meta")
        ok = status == 200
        payload = {}
        if ok:
            try:
                payload = json.loads(body)
            except ValueError:
                ok = False
        record(
            "GET /api/intelligence/meta",
            ok,
            f"status={status} keys={sorted(payload)[:6]}",
        )

        status, body = request("/api/intelligence/reliability")
        ok = status == 200
        payload = {}
        if ok:
            try:
                payload = json.loads(body)
            except ValueError:
                ok = False
        # `styles` is a list of per-style records, not a mapping.
        styles = sorted(
            row.get("style") for row in (payload.get("styles") or []) if isinstance(row, dict)
        )
        weights = {
            row.get("style"): row.get("weight")
            for row in (payload.get("styles") or [])
            if isinstance(row, dict)
        }
        record(
            "GET /api/intelligence/reliability",
            ok and styles == ["DAY_TRADING", "SCALP", "SWING"],
            f"status={status} weights={weights}",
        )

        status, body = request("/api/intelligence/auto-selection")
        payload = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        # With no engine attached the endpoint must fail safe and say so, rather
        # than returning an empty-but-successful selection.
        record(
            "GET /api/intelligence/auto-selection fails safe without an engine",
            status == 503
            and payload.get("status") == "UNAVAILABLE"
            and bool(payload.get("error")),
            f"status={status} status_field={payload.get('status')!r}",
        )

        # ── 4. Backtest endpoints ──────────────────────────────────────────
        status, body = request("/api/backtest/meta")
        ok = status == 200
        payload = {}
        if ok:
            try:
                payload = json.loads(body)
            except ValueError:
                ok = False
        record(
            "GET /api/backtest/meta",
            ok,
            f"status={status} keys={sorted(payload)[:8]}",
        )

        status, body = request("/api/backtest/jobs")
        ok = status == 200
        record("GET /api/backtest/jobs", ok, f"status={status}")

        # ── Regime policy ──────────────────────────────────────────────────
        # Either answer is correct here and both are asserted: 200 with a policy
        # table once tools/optimise_regime.py has run, or 503 UNAVAILABLE with a
        # reason when it has not. What must never happen is a 404 (route not
        # wired) or a 500 (handler raised) — and a bare 200 with no policy would
        # let a caller mistake "never run" for "nothing tradeable".
        status, body = request("/api/backtest/regime-policy")
        payload = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        if status == 200:
            ok = payload.get("status") == "OK" and isinstance(payload.get("policy"), dict)
            detail = f"status={status} modes={sorted(payload.get('policy', {}))}"
        else:
            ok = status == 503 and payload.get("status") == "UNAVAILABLE" and bool(
                payload.get("error")
            )
            detail = f"status={status} status_field={payload.get('status')!r}"
        record("GET /api/backtest/regime-policy dispatches", ok, detail)

        # The style filter must not blow up on a missing parameter, and must not
        # return modes that were not asked for.
        status, body = request("/api/backtest/regime-policy?styles=SCALP")
        payload = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        returned = set((payload.get("policy") or {}).keys())
        record(
            "GET /api/backtest/regime-policy honours ?styles=",
            status in (200, 503) and returned <= {"SCALP"},
            f"status={status} returned={sorted(returned)}",
        )

        # ── 5. POST auto-select (dry run is hard-wired) ────────────────────
        status, body = request("/api/action/auto-select", {"dry_run": True})
        payload = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        # Same fail-safe as the GET: no engine, no selection, said out loud.
        record(
            "POST /api/action/auto-select fails safe without an engine",
            status == 503 and payload.get("status") == "UNAVAILABLE",
            f"status={status} status_field={payload.get('status')!r}",
        )

        # ── 6. Submit a real backtest job ──────────────────────────────────
        status, body = request(
            "/api/backtest/run",
            {
                "label": "live-check",
                "modes": ["SWING"],
                "symbols": ["EURUSD"],
                "objective": "expectancy_r",
                "min_trades": 10,
                "passes": 1,
                "max_evaluations": 12,
            },
            timeout=60,
        )
        payload = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        # A queued job is 202 Accepted, not 200.
        job_id = payload.get("job_id") or (payload.get("job") or {}).get("job_id")
        record(
            "POST /api/backtest/run queues a job (202 Accepted)",
            status == 202 and bool(job_id),
            f"status={status} job_id={job_id}",
        )

        if job_id:
            final = None
            for _ in range(60):
                status, body = request(f"/api/backtest/jobs/{job_id}")
                try:
                    final = json.loads(body)
                except ValueError:
                    final = {}
                state = (final.get("job") or final).get("status")
                if state in ("DONE", "FAILED", "CANCELLED"):
                    break
                time.sleep(2)
            state = (final.get("job") or final).get("status")
            record(
                "the job reaches a terminal state",
                state in ("DONE", "FAILED", "CANCELLED"),
                f"status={state}",
            )

            status, body = request(f"/api/backtest/jobs/{job_id}/result")
            ok = status in (200, 404)
            record(
                "GET /api/backtest/jobs/<id>/result responds",
                ok,
                f"status={status} bytes={len(body)}",
            )

        # ── 7. Data routes behind the UI panels ────────────────────────────
        # Every panel below is fed by a route that either sits behind an
        # external provider (and can block for many seconds on a cold cache) or
        # returns modelled values. Two invariants matter more than the numbers:
        #
        #   * the route must DISPATCH. A 404 means the tab is inert: its shell
        #     renders, the click does nothing, and nothing raises.
        #   * every response must describe its own PROVENANCE. A UI cannot label
        #     what the backend does not describe, and a plausible number shown
        #     as a live quote is worse than no number at all.
        #
        # Provider routes are allowed to answer 503/504 — that is an honest
        # "provider unavailable". They are not allowed to answer 404 (unwired)
        # or 500 (handler raised).

        # 7d. /api/news — the countdown's anchor. The client corrects for clock
        # skew against the envelope's own generation time, so that value must be
        # a real ISO instant rather than a display string.
        status, body = request("/api/news", timeout=90)
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        items = payload.get("news") or []
        generated = payload.get("timestamp")
        envelope_dt = None
        try:
            envelope_dt = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            envelope_ok = envelope_dt.tzinfo is not None
        except (TypeError, ValueError):
            envelope_ok = False
        news_fields = {"timestamp_iso", "diff_seconds", "status_badge", "event",
                       "currency", "impact"}
        thin = [i for i, ev in enumerate(items) if not news_fields <= set(ev)]
        record(
            "GET /api/news carries the fields the countdown is built from",
            status == 200 and bool(items) and not thin and envelope_ok,
            f"status={status} events={len(items)} envelope={generated!r} thin={thin[:3]}",
        )

        # 7e. The sign of diff_seconds must agree with timestamp_iso measured
        # against the envelope's own generation time. If the two disagree, the
        # client's locally-derived countdown contradicts the server's and a row
        # flips phase at the wrong moment — which is exactly why deriving the
        # countdown client-side is only safe when this holds.
        disagree = []
        if envelope_dt is not None:
            for ev in items[:12]:
                iso, diff = ev.get("timestamp_iso"), ev.get("diff_seconds")
                if iso is None or diff is None:
                    continue
                try:
                    event_dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
                except ValueError:
                    disagree.append((iso, "unparseable"))
                    continue
                expected = (event_dt - envelope_dt).total_seconds()
                # Same side of zero, and within the couple of seconds the
                # payload takes to travel.
                if (expected > 0) != (float(diff) > 0) or abs(expected - float(diff)) > 120:
                    disagree.append((ev.get("event"), diff, round(expected, 1)))
        record(
            "the server's diff_seconds agrees with its own timestamp_iso",
            envelope_ok and not disagree,
            f"disagreements={disagree[:3]}" if disagree
            else f"{min(len(items), 12)} events consistent",
        )

        # ── 8. Attach a real orchestrator and re-check the live path ───────
        try:
            from jarvis.api.server import JarvisRequestHandler
            from jarvis.application.orchestrator import JarvisOrchestrator

            orchestrator = JarvisOrchestrator(
                symbols=["EURUSD"], mode="paper", trade_style="SWING"
            )
            JarvisRequestHandler.configure_orchestrator(orchestrator)

            status, body = request("/api/intelligence/meta")
            meta = json.loads(body) if status == 200 else {}
            record(
                "configure_orchestrator reaches the intelligence service",
                status == 200 and meta.get("orchestrator_attached") is True,
                f"status={status} attached={meta.get('orchestrator_attached')}",
            )

            status, body = request(
                "/api/intelligence/auto-selection?symbols=EURUSD&styles=SWING",
                timeout=240,
            )
            payload = {}
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            record(
                "GET /api/intelligence/auto-selection with an engine attached",
                status == 200 and payload.get("status") == "OK",
                f"status={status} field={payload.get('status')!r} "
                f"decisions={len(payload.get('decisions') or [])} "
                f"error={str(payload.get('error'))[:80]!r}",
            )

            # The HTTP path must never be able to open a trade.
            if status == 200:
                record(
                    "auto-selection is hard-wired to dry_run",
                    payload.get("dry_run") is True,
                    f"dry_run={payload.get('dry_run')!r}",
                )

            status, body = request(
                "/api/action/auto-select",
                {"dry_run": False, "symbols": ["EURUSD"], "styles": ["SWING"]},
                timeout=240,
            )
            payload = {}
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            record(
                "POST /api/action/auto-select ignores dry_run=False",
                status in (200, 503) and payload.get("dry_run") is True,
                f"status={status} dry_run={payload.get('dry_run')!r} "
                f"ignored={payload.get('requested_dry_run_ignored')!r}",
            )
        except Exception as exc:  # noqa: BLE001 - report, do not mask
            record(
                "attach a real orchestrator and re-check the live path",
                False,
                f"{type(exc).__name__}: {exc}",
            )

        # ── 9. Copilot: the route answers, and dispatches by intent ────────
        # This endpoint had no probe and its module had no tests, so a routing
        # regression reached the trader unchallenged. A plain answer and the
        # intent dispatch are both checked, because the failure this endpoint
        # has actually shipped was a wrong-but-plausible answer rather than an
        # error: "how are my trades doing?" returned one instrument's position
        # status.
        status, body = request("/api/copilot/ask", {"query": ""})
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        answer = payload.get("response") or ""
        record(
            "POST /api/copilot/ask answers with a response body",
            status == 200 and len(answer) > 40,
            f"status={status} chars={len(answer)}",
        )

        status, body = request(
            "/api/copilot/ask",
            {"query": "how are my trades doing?", "context": {"symbol": "XAUUSD"}},
        )
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        answer = payload.get("response") or ""
        record(
            "the copilot answers a book-level question about the book",
            status == 200 and "How you stand" in answer and "no open position" not in answer,
            f"status={status} book_answer={'How you stand' in answer}",
        )

        # ── 10. Unknown route still 404s ───────────────────────────────────
        status, _ = request("/api/backtest/nonsense")
        record("unknown backtest route 404s", status == 404, f"status={status}")

    finally:
        server.shutdown()
        server.server_close()

    failures = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(failures)}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
