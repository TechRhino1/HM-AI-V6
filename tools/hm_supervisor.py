"""Keep HM_start.py running: restart it with backoff whenever it exits non-zero, or hangs.

Usage: python tools/hm_supervisor.py [HM_start args...]   e.g.  python tools/hm_supervisor.py demo
Exit code 0 from the engine (clean Ctrl-C / SIGTERM shutdown) stops the supervisor.
During a restart backoff, close the window (or end the scheduled task) to stop it.

Hang probe (2026-11-27): a crash was the only thing restarted before; a hung engine (dead
orchestration loop, stopped monitor, no HTTP answer) sat there trading nothing. After a 5 min
start-up grace the supervisor polls /health every 30 s and restarts the engine only when the
endpoint is unreachable for 5 min, or the loop heartbeat is CRITICAL / the monitor stale for
10 min. Lesser warnings never restart it. A restart is safe for risk state: the daily-loss
lockout is rebuilt from the trade history and open positions keep their broker stops.
"""
import json
import logging
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib import error as urllib_error
from urllib import request as urllib_request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LONG_RUN_S = 600  # a run this long counts as healthy and resets the backoff
STARTUP_GRACE_S = 300.0
PROBE_EVERY_S = 30.0
UNREACHABLE_S = 300.0
STALLED_S = 600.0
HUNG_EXIT = 75  # non-zero: the supervisor restarts with backoff
logger = logging.getLogger("HM_SUPERVISOR")


def health_url(argv) -> str:
    port = os.environ.get("JARVIS_PORT", os.environ.get("PORT", "8501"))
    for arg in argv:
        if str(arg).isdigit():
            port = arg
        elif str(arg).startswith("--port="):
            port = arg.split("=", 1)[1]
    return f"http://127.0.0.1:{port}/health"


def fetch_health(url: str):
    """The /health JSON (a 503 still carries one), or None when the engine does not answer."""
    try:
        with urllib_request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {}
    except Exception:
        return None


def hang_verdict(body, state: dict, now: float):
    """Why the engine counts as hung, or None. `state` carries first-seen times between probes."""
    if body is None:
        state.setdefault("unreachable", now)
        return (f"health endpoint unreachable for {now - state['unreachable']:.0f}s"
                if now - state["unreachable"] >= UNREACHABLE_S else None)
    state.pop("unreachable", None)
    stalled = ((body.get("loop") or {}).get("status") == "CRITICAL") or bool(body.get("monitor_stale"))
    if not stalled:
        state.pop("stalled", None)
        return None
    state.setdefault("stalled", now)
    return (f"orchestration loop stalled or monitor stale for {now - state['stalled']:.0f}s"
            if now - state["stalled"] >= STALLED_S else None)


def run_with_probe(cmd, cwd, url, fetch=fetch_health, sleep=time.sleep, clock=time.monotonic, popen=subprocess.Popen):
    proc = popen(cmd, cwd=cwd)
    started, state = clock(), {}
    while proc.poll() is None:
        sleep(PROBE_EVERY_S)
        if clock() - started < STARTUP_GRACE_S:
            continue
        why = hang_verdict(fetch(url), state, clock())
        if why:
            logger.error("HM engine hung (%s); terminating it for a restart", why)
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except Exception:
                proc.kill()
            return SimpleNamespace(returncode=HUNG_EXIT)
    return SimpleNamespace(returncode=proc.returncode)


def supervise(argv, run=None, sleep=time.sleep, clock=time.monotonic) -> int:
    url = health_url(argv)
    if run is None:
        def run(cmd, cwd):
            return run_with_probe(cmd, cwd, url)
    n = 0
    while True:
        started = clock()
        code = run([sys.executable, "HM_start.py", *argv], cwd=REPO_ROOT).returncode
        if code == 0:
            logger.info("HM engine exited cleanly; supervisor stopping")
            return 0
        if clock() - started > LONG_RUN_S:
            n = 0
        delay = min(300, 5 * 2 ** n)
        n += 1
        logger.warning("HM engine exited with code %s; restarting in %ss", code, delay)
        sleep(delay)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    # Ctrl-C reaches both processes on a shared console; without this, subprocess.run
    # kills the engine 0.25s later, mid-shutdown. The engine exits 0, which stops us.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sys.exit(supervise(sys.argv[1:]))
