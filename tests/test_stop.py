"""Tombol Stop: Tarik Chat berhenti di tengah dengan hasil sebagian, Generate menghentikan proses Claude."""

import subprocess

import pytest

from core import claude_ai
from core.cancel import Cancelled
from core.reader import WhatsApp


def test_read_chats_stops_and_keeps_partial_result(monkeypatch):
    stop = {"now": False}
    wa = WhatsApp("unused", should_stop=lambda: stop["now"])
    monkeypatch.setattr(wa, "open_chat", lambda name: True)

    def read(since):
        stop["now"] = True          # user menekan Stop setelah chat pertama terbaca
        return [{"text": "x"}]

    monkeypatch.setattr(wa, "read_messages", read)
    monkeypatch.setattr("core.reader._pause", lambda *a: None)
    out = wa.read_chats(["A", "B", "C"], since=None)
    assert list(out) == ["A"] and wa.stopped is True


class _SlowProc:
    killed = False

    def __init__(self, *a, **kw):
        self.returncode = None

    def communicate(self, input=None, timeout=None):
        if _SlowProc.killed:
            return "", ""
        raise subprocess.TimeoutExpired("claude", timeout)

    def kill(self):
        _SlowProc.killed = True


def test_generate_kills_claude_on_stop(monkeypatch):
    monkeypatch.setattr(claude_ai.subprocess, "Popen", _SlowProc)
    calls = {"n": 0}

    def should_stop():
        calls["n"] += 1
        return calls["n"] >= 2

    with pytest.raises(Cancelled):
        claude_ai.generate("claude", "prompt", "Daily Report", timeout=60, should_stop=should_stop)
    assert _SlowProc.killed
