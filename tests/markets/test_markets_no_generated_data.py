"""The market adviser must never generate, randomise or hard-code market data (your explicit requirement).

Static scan of every module under jarvis/markets/: any random source, symbol-hash
derived value or synthetic fallback fails the build.
"""
import re
from pathlib import Path

ROOTS = [Path(__file__).resolve().parents[2] / "jarvis" / "markets", Path(__file__).resolve().parents[2] / "jarvis" / "ai"]
BANNED = [
    (r"\bimport random\b|\bfrom random\b", "random module"),
    (r"np\.random|numpy\.random|default_rng", "numpy random"),
    (r"\buniform\(|\bgauss\(|\brandint\(", "random draw"),
    (r"\bhash\(", "hash-derived value"),
    (r"synthetic|sample_data|dummy|placeholder_price|base_price", "synthetic/sample/placeholder data"),
]


def test_no_generator_in_markets_package():
    assert all(r.is_dir() for r in ROOTS)
    hits = []
    for py in (p for r in ROOTS for p in r.rglob("*.py")):
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            for pat, what in BANNED:
                if re.search(pat, code, re.IGNORECASE):
                    hits.append(f"{py.relative_to(ROOTS[0].parent.parent)}:{n} {what}: {line.strip()}")
    assert not hits, "generated/dummy data found:\n" + "\n".join(hits)
