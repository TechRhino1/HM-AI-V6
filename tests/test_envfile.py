"""The .env loader: comments, quotes, BOM, and the real environment always wins."""
import os

from jarvis.common.envfile import load_env


def test_load_env(tmp_path, monkeypatch):
    for k in ("HM_T_A", "HM_T_B", "HM_T_C", "HM_T_D", "HM_T_E", "HM_T_EMPTY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HM_T_D", "from-shell")
    f = tmp_path / ".env"
    f.write_text('﻿# comment\nHM_T_A=plain\nexport HM_T_B="quoted # kept"\nHM_T_C=val # note\n'
                 "HM_T_D=from-file\nHM_T_E='single'\nHM_T_EMPTY=\nnot a line\n", encoding="utf-8")
    loaded = load_env(f)
    for k in loaded:  # monkeypatch didn't set these, so clean them up after
        monkeypatch.setenv(k, os.environ[k])
    assert sorted(loaded) == ["HM_T_A", "HM_T_B", "HM_T_C", "HM_T_E"]
    assert (os.environ["HM_T_A"], os.environ["HM_T_B"], os.environ["HM_T_C"], os.environ["HM_T_E"]) == ("plain", "quoted # kept", "val", "single")
    assert os.environ["HM_T_D"] == "from-shell" and "HM_T_EMPTY" not in os.environ


def test_missing_file_is_fine(tmp_path):
    assert load_env(tmp_path / "nope.env") == []
