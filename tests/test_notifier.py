import subprocess

import pytest

from rabot.notifier import SignalNotifier


def _capture(monkeypatch):
    captured = {}

    def fake_run(cmd, check, capture_output, text):
        captured["cmd"] = cmd
        captured["check"] = check
        class R: returncode = 0; stderr = ""
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


def test_builds_correct_signal_cli_command(monkeypatch):
    captured = _capture(monkeypatch)
    SignalNotifier("signal-cli", "+15550000001", "+15550000002").send("hello")
    assert captured["cmd"] == [
        "signal-cli", "-u", "+15550000001", "send", "-m", "hello", "+15550000002"
    ]
    assert captured["check"] is True


def test_group_send_uses_g_flag_not_recipient(monkeypatch):
    captured = _capture(monkeypatch)
    SignalNotifier("signal-cli", "+15550000001", group_id="GROUPID==").send("hi group")
    assert captured["cmd"] == [
        "signal-cli", "-u", "+15550000001", "send", "-m", "hi group", "-g", "GROUPID=="
    ]


def test_requires_recipient_or_group():
    with pytest.raises(ValueError, match="recipient or a group"):
        SignalNotifier("signal-cli", "+1")


def test_send_raises_on_failure(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, stderr="link expired")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        SignalNotifier("signal-cli", "+1", "+2").send("hi")
