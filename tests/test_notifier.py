import subprocess

import pytest

from rabot.notifier import SignalNotifier, link


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


def test_no_sender_omits_u_flag(monkeypatch):
    captured = _capture(monkeypatch)
    SignalNotifier("signal-cli", recipient="+15550000002").send("hi")  # no sender
    assert captured["cmd"] == ["signal-cli", "send", "-m", "hi", "+15550000002"]


def test_requires_recipient_or_group():
    with pytest.raises(ValueError, match="recipient or a group"):
        SignalNotifier("signal-cli")


def test_send_raises_on_failure(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, stderr="link expired")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        SignalNotifier("signal-cli", "+1", "+2").send("hi")


class _FakeProc:
    def __init__(self, lines, rc=0):
        self.stdout = iter(lines)
        self._rc = rc

    def wait(self):
        return self._rc


def test_link_runs_signal_cli_and_renders_qr_from_uri():
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeProc([
            "Some signal-cli preamble\n",
            "sgnl://linkdevice?uuid=abc%3D%3D&pub_key=xyz\n",
            "Associated with: +15550000001\n",
        ])

    rendered = []
    rc = link("signal-cli", "rabot-host",
              popen=fake_popen, render_qr=rendered.append)

    assert rc == 0
    assert seen["cmd"] == ["signal-cli", "link", "-n", "rabot-host"]
    assert rendered == ["sgnl://linkdevice?uuid=abc%3D%3D&pub_key=xyz"]


def test_link_returns_nonzero_exit_when_signal_cli_fails():
    def fake_popen(cmd, **kwargs):
        return _FakeProc(["Link request error: Connection closed!\n"], rc=3)

    rc = link("signal-cli", "rabot-host", popen=fake_popen, render_qr=lambda u: None)
    assert rc == 3
