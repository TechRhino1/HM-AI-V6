"""
Automated Repository-Wide Module Import Smoke Test
Dynamically scans and imports every Python source file in the repository (excluding tests/scratch)
to catch NameError, ImportError, AttributeError, and syntax issues at class/module definition time.
"""
import os
import sys
import importlib
import pytest

def test_all_modules_import_cleanly():
    # Importing a script must not leak process state into later tests (it used to set
    # JARVIS_BACKTEST_MODE and logging.disable(CRITICAL), failing ~11 unrelated tests).
    import logging
    env_before, disable_before = dict(os.environ), logging.root.manager.disable
    try:
        _sweep()
    finally:
        os.environ.clear()
        os.environ.update(env_before)
        logging.disable(disable_before)


def _sweep():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    broken_modules = []
    checked_count = 0

    for root, dirs, files in os.walk(repo_root):
        # Exclude git, cache, tests, scratch, and .gemini directories
        dirs[:] = [
            d for d in dirs
            if d not in [".git", "__pycache__", ".pytest_cache", ".gemini", ".scratch", "scratch", "venv", ".venv", "Python315Libsite-packages", "legacy_audits"]
            and "site-packages" not in d.lower()
        ]
        
        rel_root = os.path.relpath(root, repo_root)
        if rel_root.startswith("tests") or rel_root.startswith("."):
            continue

        for f in files:
            if f.endswith(".py") and not f.startswith("test_") and not f.startswith("check_"):
                file_path = os.path.join(root, f)
                rel_path = os.path.relpath(file_path, repo_root)
                # Convert path to module format
                mod_name = os.path.splitext(rel_path)[0].replace(os.path.sep, ".")
                
                try:
                    checked_count += 1
                    importlib.import_module(mod_name)
                except Exception as e:
                    broken_modules.append((mod_name, str(e)))

    print(f"Import Sweep Complete: {checked_count} modules verified.")
    if broken_modules:
        for mod, err in broken_modules:
            print(f"BROKEN MODULE: {mod} -> {err}")
    
    assert len(broken_modules) == 0, f"Found {len(broken_modules)} broken module(s): {broken_modules}"

if __name__ == "__main__":
    test_all_modules_import_cleanly()
    print("ALL MODULES IMPORTED SUCCESSFULLY!")
