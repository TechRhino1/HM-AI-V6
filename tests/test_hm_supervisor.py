import sys
from types import SimpleNamespace

from tools.hm_supervisor import supervise


def _fake(codes, durations):
    calls, sleeps, now = [], [], [0.0]
    codes, durations = iter(codes), iter(durations)

    def run(cmd, cwd):
        calls.append(cmd)
        now[0] += next(durations)
        return SimpleNamespace(returncode=next(codes))

    return calls, sleeps, run, sleeps.append, (lambda: now[0])


def test_restarts_with_exponential_backoff_until_clean_exit():
    calls, sleeps, run, sleep, clock = _fake([1, 1, 0], [1, 1, 1])
    assert supervise(["demo"], run=run, sleep=sleep, clock=clock) == 0
    assert len(calls) == 3 and calls[0][-2:] == ["HM_start.py", "demo"]
    assert sleeps == [5, 10]


def test_long_run_resets_backoff_and_delay_is_capped():
    calls, sleeps, run, sleep, clock = _fake([1] * 8 + [1, 0], [1] * 8 + [3600, 1])
    supervise([], run=run, sleep=sleep, clock=clock)
    assert sleeps == [5, 10, 20, 40, 80, 160, 300, 300, 5]


def test_keep_awake_is_noop_off_windows(monkeypatch):
    import HM_start

    monkeypatch.setattr(sys, "platform", "linux")
    assert HM_start._keep_awake(True) is False
    assert HM_start._keep_awake(False) is False
