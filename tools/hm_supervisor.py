"""Keep HM_start.py running: restart it with backoff whenever it exits non-zero.

Usage: python tools/hm_supervisor.py [HM_start args...]   e.g.  python tools/hm_supervisor.py demo
Exit code 0 from the engine (clean Ctrl-C / SIGTERM shutdown) stops the supervisor.
During a restart backoff, close the window (or end the scheduled task) to stop it.
"""
import logging
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LONG_RUN_S = 600  # a run this long counts as healthy and resets the backoff
logger = logging.getLogger("HM_SUPERVISOR")


def supervise(argv, run=subprocess.run, sleep=time.sleep, clock=time.monotonic) -> int:
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
