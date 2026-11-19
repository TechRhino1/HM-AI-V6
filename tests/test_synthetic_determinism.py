"""
A "stable" seed must be identical in every process. ``hash()`` is salted per
process (PYTHONHASHSEED), so a hash-derived seed yields a different value on
every interpreter start. ``stable_seed`` (jarvis/data/determinism.py) is the
single definition of the replacement.
"""
import ast
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestStableSeedHelper(unittest.TestCase):
    def test_helper_has_exactly_one_definition(self):
        definitions = []
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "jarvis")):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                for node in ast.walk(ast.parse(_read(path))):
                    if isinstance(node, ast.FunctionDef) and node.name == "stable_seed":
                        definitions.append(os.path.relpath(path, REPO_ROOT))
        self.assertEqual(
            definitions, [os.path.join("jarvis", "data", "determinism.py")],
            "stable_seed must have exactly one definition",
        )

    def test_helper_is_a_plain_function_of_the_text(self):
        from jarvis.data.determinism import stable_seed

        self.assertEqual(
            stable_seed("RELIANCE"),
            sum((i + 1) * ord(c) for i, c in enumerate("RELIANCE")) % 100000,
        )
        # It must not actually *call* hash() — that is the whole point.
        # (Its docstring mentions hash() by name, so parse rather than grep.)
        path = os.path.join(REPO_ROOT, "jarvis", "data", "determinism.py")
        tree = ast.parse(_read(path))
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "stable_seed"
        )
        called = {
            n.func.id for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertNotIn("hash", called, "stable_seed must not call hash()")



if __name__ == "__main__":
    unittest.main()
