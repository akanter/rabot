import re
import subprocess
import sys


class SignalNotifier:
    def __init__(self, signal_cli_path: str, sender: str,
                 recipient: str | None = None, group_id: str | None = None):
        if not recipient and not group_id:
            raise ValueError("SignalNotifier needs a recipient or a group_id")
        self.signal_cli_path = signal_cli_path
        self.sender = sender
        self.recipient = recipient
        self.group_id = group_id

    def send(self, message: str) -> None:
        cmd = [self.signal_cli_path, "-u", self.sender, "send", "-m", message]
        # A group send uses `-g <id>` and takes no positional recipient.
        if self.group_id:
            cmd += ["-g", self.group_id]
        else:
            cmd.append(self.recipient)
        subprocess.run(cmd, check=True, capture_output=True, text=True)


_LINK_URI = re.compile(r"(?:sgnl://|tsdevice:/)\S+")


def render_link_qr(uri: str) -> None:
    """Show the linking QR in the terminal (via qrencode), with the URI as fallback."""
    print("\nScan this QR in Signal → Settings → Linked Devices → +:\n", flush=True)
    try:
        subprocess.run(["qrencode", "-t", "UTF8", "-m", "2", uri], check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("(qrencode unavailable — paste this URI into a QR generator)")
    print(f"\nLink URI: {uri}\n", flush=True)


def link(signal_cli_path: str, device_name: str, *,
         popen=subprocess.Popen, render_qr=render_link_qr) -> int:
    """Run `signal-cli link`, render the link QR when it appears, and wait.

    Returns signal-cli's exit code (0 once the phone completes linking).
    """
    proc = popen(
        [signal_cli_path, "link", "-n", device_name],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    for line in proc.stdout:
        match = _LINK_URI.search(line)
        if match:
            render_qr(match.group(0))
        else:
            sys.stdout.write(line)
    return proc.wait()
