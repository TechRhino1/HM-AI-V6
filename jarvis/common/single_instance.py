"""One trading engine per mode.

Two engines on the same account would both see the same setup and both send
the order. The lock is an OS file lock, so it is released automatically if the
process dies — there is no stale lock file to clean up.
"""
import os
import sys

_HELD = []  # keep handles alive for the life of the process


class AlreadyRunningError(RuntimeError):
    pass


def acquire_engine_lock(mode: str, lock_dir: str = "data") -> None:
    os.makedirs(lock_dir, exist_ok=True)
    path = os.path.join(lock_dir, f".engine_{mode}.lock")
    fh = open(path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise AlreadyRunningError(
            f"Another HM Algo engine is already running in '{mode}' mode ({path}). "
            "Stop it first: two engines on one account would place duplicate orders."
        )
    fh.seek(0); fh.truncate(); fh.write(str(os.getpid())); fh.flush()
    _HELD.append(fh)


def install_shutdown_signals() -> None:
    """Route SIGTERM / Ctrl-Break / console close into the existing Ctrl-C shutdown path."""
    import signal

    def _raise(*_):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _raise)
            except (ValueError, OSError):
                pass  # not the main thread / unsupported here
