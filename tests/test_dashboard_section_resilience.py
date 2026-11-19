"""No silent empty panels.

Every panel that loads on a cold tab silently returned on a failed GET.
History and missed-trades were worse: a transport failure rendered as
"no trades" and "all setups passed filters" -- an all-clear the data did not
support. The source-level tests below pin that the SPA sections polling
those endpoints render the poll's error, not just an empty state.
"""

import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPA_FEATURES = os.path.join(REPO_ROOT, "frontend", "src", "features")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestSectionsSurfaceLoadFailures:
    """A failed poll must be shown as an error, not as an empty or all-clear panel.

    ``usePoll`` keeps the failure in ``.error``; a section that never renders it
    turns an outage into "nothing to show".
    """

    @pytest.mark.parametrize("rel_path,endpoint", [
        ("news/News.tsx", "/api/news"),
        ("trade/ChartPanel.tsx", "/api/candles"),
        ("analytics/Calibration.tsx", "/api/intelligence/calibration"),
        ("analytics/Research.tsx", "/api/intelligence/symbol-profiles"),
        ("analytics/Research.tsx", "/api/intelligence/missed-trades"),
        ("portfolio/Journal.tsx", "/api/history"),
        ("analytics/Lab.tsx", "/api/backtest/meta"),
    ])
    def test_section_renders_the_poll_error(self, rel_path, endpoint):
        src = _read(os.path.join(SPA_FEATURES, *rel_path.split("/")))
        m = re.search(r"const (\w+) = usePoll<[^(]*>\(\s*[\"'`]" + re.escape(endpoint), src)
        assert m, f"no usePoll of {endpoint} in {rel_path}"
        assert f"error={{{m.group(1)}.error" in src, \
            f"{rel_path} polls {endpoint} but never renders {m.group(1)}.error"

    def test_missed_trades_failure_is_not_an_all_clear(self):
        src = _read(os.path.join(SPA_FEATURES, "analytics", "Research.tsx"))
        assert "All evaluated setups passed filters" not in src
