"""Load KEY=VALUE lines from the project's .env into os.environ (stdlib only; real environment always wins)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Optional[os.PathLike] = None) -> List[str]:
    """Set variables from `path` (default: <project>/.env) that are not already set. Returns the names loaded, never values."""
    p = Path(path) if path else ROOT / ".env"
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    loaded = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.removeprefix("export ").partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key and val and not os.environ.get(key):
            os.environ[key] = val
            loaded.append(key)
    return loaded
