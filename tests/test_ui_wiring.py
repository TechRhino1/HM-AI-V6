"""
UI <-> API wiring contract for the dashboard SPA (``frontend/src``).

Each test here pins a defect that was real, silent, and invisible to every
existing test (found in the old server-rendered dashboard, kept for the SPA):

1. The UI asked /api/candles for ``timeframe=`` while the handler read
   ``tf=``. The endpoint answered 200 with H1 candles every time, so the
   timeframe selector looked like it worked and did nothing. A 200 is not
   evidence that a parameter was honoured.

2. The positions table read ``p.price_open`` / ``p.price_current``, but the
   backend serialises ``open_price`` / ``current_price``. An undefined field
   renders a dash, so the Entry and Now columns were permanently blank with no
   error. Every position field the SPA reads must therefore be one the schema
   actually serialises.

These are cheap, source-level invariants: no server, no browser, no fixtures.
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPA_SRC = os.path.join(REPO_ROOT, "frontend", "src")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _spa_sources():
    """(relative path, source) for every .ts/.tsx file in the SPA."""
    for dirpath, _dirs, files in os.walk(SPA_SRC):
        for name in sorted(files):
            if name.endswith((".ts", ".tsx")):
                path = os.path.join(dirpath, name)
                yield os.path.relpath(path, SPA_SRC).replace(os.sep, "/"), _read(path)


class TestCandlesQueryParameter(unittest.TestCase):
    """Every UI caller must send the parameter the handler actually reads."""

    def test_no_caller_uses_the_unread_parameter_name(self):
        offenders = {}
        for name, src in _spa_sources():
            for match in re.finditer(r"/api/candles\?[^'\"`\s]*", src):
                url = match.group(0)
                if "timeframe=" in url:
                    offenders.setdefault(name, []).append(url[:80])
        self.assertEqual(
            offenders, {},
            f"these calls use a parameter /api/candles does not read: {offenders}",
        )

    def test_every_caller_sends_tf(self):
        callers = []
        for name, src in _spa_sources():
            for match in re.finditer(r"/api/candles\?[^'\"`\s]*", src):
                url = match.group(0)
                callers.append((name, "?tf=" in url or "&tf=" in url))
        self.assertTrue(callers, "expected at least one caller of /api/candles")
        missing = [n for n, ok in callers if not ok]
        self.assertEqual(missing, [], f"callers not sending tf=: {missing}")

    def test_handler_accepts_both_spellings(self):
        """The route should tolerate the longer name like its siblings do."""
        src = _read(os.path.join(REPO_ROOT, "jarvis", "api", "server.py"))
        self.assertIn(
            'query.get("tf", query.get("timeframe"', src,
            "/api/candles should accept both tf and timeframe, as /api/rates does",
        )


class TestPositionFieldNames(unittest.TestCase):
    """The SPA must read the field names the backend actually serialises."""

    OPEN_POSITIONS = os.path.join(SPA_SRC, "features", "portfolio", "OpenPositions.tsx")

    def _serialised_position_fields(self):
        src = _read(os.path.join(REPO_ROOT, "jarvis", "data", "schemas.py"))
        anchor = src.index('"open_price": self.open_price')
        block = src[src.rindex("def to_dict", 0, anchor):src.index("}", anchor)]
        return set(re.findall(r'"([a-z_0-9]+)":\s*self\.', block))

    def test_positions_table_uses_serialised_position_fields(self):
        src = _read(self.OPEN_POSITIONS)
        self.assertNotIn("p.price_open", src)
        self.assertNotIn("p.price_current", src)
        self.assertIn("p.open_price", src)
        self.assertIn("p.current_price", src)

    def test_every_position_field_the_table_reads_is_serialised(self):
        reads = set(re.findall(r"(?<![A-Za-z0-9_.])p\.([a-z_][a-z_0-9]*)", _read(self.OPEN_POSITIONS)))
        self.assertTrue(reads, "expected OpenPositions.tsx to read position fields")
        missing = sorted(reads - self._serialised_position_fields())
        self.assertEqual(
            missing, [],
            f"OpenPositions.tsx reads fields PositionSnapshot.to_dict does not emit: {missing}",
        )

    def test_schema_serialises_those_exact_names(self):
        """Guard the guard: if the schema renames, the positions table breaks again."""
        fields = self._serialised_position_fields()
        for name in ("open_price", "current_price", "sl", "tp", "profit", "ticket",
                     "type", "volume", "is_be_locked", "monitoring_mode", "comment"):
            self.assertIn(name, fields)


if __name__ == "__main__":
    unittest.main()
