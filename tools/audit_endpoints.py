"""Cross-check every endpoint the UI calls against the running server.

A UI call that 404s is a dead button: the JavaScript asks for something the
server does not dispatch. This is the definitive test — it does not rely on
parsing either side correctly, it just asks the server.

Usage (from the repo root, with the server running):

    python tools/audit_endpoints.py                      # defaults to :8501
    python tools/audit_endpoints.py --base http://127.0.0.1:8599
    python tools/audit_endpoints.py --start-server       # boot one on :8599
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The React SPA in frontend/ (built into jarvis/ui/static/app). Tests hold no real calls.
JS_GLOBS = ["frontend/src/**/*.ts", "frontend/src/**/*.tsx"]
SKIP = {".test."}
# `api.post("/api/...")` marks a POST route; anything else is probed with GET.
POST_CALL = re.compile(r"""\bpost\s*(?:<[^()]*?>)?\s*\(\s*["'`](/api/[A-Za-z0-9_/.\-]*)""")
# Routes that exist but must not be probed: they write state or take minutes.
NO_PROBE = {
    "/api/ai/brief/generate": "writes a brief and takes up to a minute",
    "/api/markets/fno/scan": "scans every F&O underlying (10-60 s)",
}
# Routes that legitimately take longer than the default 20 s leash (seconds).
SLOW = {"/api/markets/inst/delivery": 150}  # rebuilds the 20-session bhavdata screen

# Endpoints that are POST-only. Probing these with GET returns 404 by design —
# the route exists but is not dispatched on GET — so the audit must use POST or
# it reports a working endpoint as dead.
POST_ONLY = {
    "/api/action/cancel_pending_order",
    "/api/action/close_all_positions",
    "/api/action/close_position",
    "/api/action/manual_trade",
    "/api/action/modify_pending_order",
    "/api/action/place_pending_order",
    "/api/action/set_mode",
    "/api/action/set_trade_style",
    "/api/action/toggle_safe_mode",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/verify",
    "/api/backtest/cancel",
    "/api/backtest/run",
    "/api/copilot/ask",
    "/api/ai/chat/stream",  # called with fetch(), not api.post()
}

# Routes that reach a live external provider (NSE / equity data). They get a
# short leash, because a provider stall is indefinite rather than merely slow.
#
# These were previously reported as "hang rather than fail" and tolerated, on
# the theory that a sandbox without outbound access would hang on them. That was
# wrong twice over. Outbound access works here, and the reason three of them
# (heatmap, indices, scanner) never answered was a defect in this repo: an
# unbounded fetch_quotes -> get_india_profile -> get_profile -> hydrate_batch
# cycle, fixed in 2c655c6 but still running in a server process that predated
# the commit. Tolerating the timeout meant this tool could not see the very bug
# it exists to catch. All six answer in well under the leash now.
#
# So a timeout here is reported as HANG and fails the run. Use
# --allow-provider-hang only in a genuinely air-gapped environment.
EXTERNAL: set[str] = set()  # the NSE / US-equity routes that lived here were removed

# Endpoints that need a query parameter to be meaningful. Requesting them bare
# is expected to 400, not 404; the point is to prove the route is dispatched.
NEEDS_PARAMS = {
    "/api/candles": "symbol=EURUSD&timeframe=H1",
    "/api/radar": "symbol=EURUSD",
    "/api/history": "symbol=EURUSD",
}


def ui_endpoints() -> list[str]:
    """Every /api path the SPA references (query strings and `${...}` suffixes cut off); POST ones join POST_ONLY."""
    found: set[str] = set()
    for pattern in JS_GLOBS:
        for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            if any(s in os.path.basename(path) for s in SKIP):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            POST_ONLY.update(m.group(1) for m in POST_CALL.finditer(text))
            for m in re.finditer(r"""["'`](/api/[A-Za-z0-9_/.\-]*)""", text):
                url = m.group(1)
                # Prefixes such as "/api/ai/" in a startsWith() are not calls.
                if url.endswith("/"):
                    continue
                found.add(url)
    return sorted(found)


def probe(base: str, path: str, method: str = "GET", timeout: int = 20) -> tuple[int, str]:
    url = base + path
    data = b"{}" if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:160]
        except Exception:
            pass
        return exc.code, body
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8501")
    ap.add_argument("--start-server", action="store_true")
    ap.add_argument("--port", type=int, default=8599)
    ap.add_argument(
        "--allow-provider-hang",
        action="store_true",
        help="tolerate a timeout on a provider-backed route (air-gapped hosts "
             "only; by default a hang is a failure)",
    )
    args = ap.parse_args()

    proc = None
    base = args.base
    if args.start_server:
        base = f"http://127.0.0.1:{args.port}"
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "from jarvis.api.server import start_server; "
             f"start_server(host='127.0.0.1', port={args.port}, mt5_client=None).serve_forever()"],
            cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(6)

    try:
        endpoints = ui_endpoints()
        print(f"UI endpoints found : {len(endpoints)}")
        print(f"probing            : {base}")
        print("=" * 78)

        dead: list[tuple[str, int, str]] = []
        external: list[tuple[str, str]] = []
        ok = 0
        for path in endpoints:
            if path in NO_PROBE:
                print(f"skip  {path}  ({NO_PROBE[path]})")
                continue
            q = NEEDS_PARAMS.get(path, "")
            target = f"{path}?{q}" if q else path
            method = "POST" if path in POST_ONLY else "GET"
            # Provider-backed routes get a short leash; a stall there is
            # indefinite, and this run should not wait on it.
            timeout = 6 if path in EXTERNAL else SLOW.get(path, 20)
            status, body = probe(base, target, method=method, timeout=timeout)

            # An app-level 404 answers JSON ("no brief yet"); an undispatched route gets the HTML error page.
            if status == 404 and not body.lstrip().startswith("{"):
                dead.append((path, status, body))
                print(f"DEAD  {method} {path}")
                if body:
                    print(f"        {body[:120]}")
            elif status == -1:
                if path in EXTERNAL and args.allow_provider_hang:
                    external.append((path, body))
                    print(f"EXT   {path}  (provider unreachable, tolerated by flag)")
                else:
                    # A provider-backed route that does not answer is a finding,
                    # not an excuse. This is the symptom that hid a live defect.
                    dead.append((path, status, body))
                    label = "HANG" if path in EXTERNAL else "ERR "
                    print(f"{label}  {method} {path}  {body[:100]}")
            else:
                ok += 1
                print(f"  ok  {method} {path}  -> {status}")

        print("=" * 78)
        print(f"dispatched        : {ok}/{len(endpoints) - len(NO_PROBE.keys() & set(endpoints))}  (+{len(NO_PROBE.keys() & set(endpoints))} not probed)")
        print(f"external-provider : {len(external)}  (tolerated by --allow-provider-hang)")
        print(f"dead/error        : {len(dead)}")
        return 1 if dead else 0
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
