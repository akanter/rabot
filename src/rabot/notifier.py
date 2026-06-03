import subprocess


class SignalNotifier:
    def __init__(self, signal_cli_path: str, sender: str, recipient: str):
        self.signal_cli_path = signal_cli_path
        self.sender = sender
        self.recipient = recipient

    def send(self, message: str) -> None:
        subprocess.run(
            [self.signal_cli_path, "-u", self.sender, "send", "-m", message, self.recipient],
            check=True,
            capture_output=True,
            text=True,
        )
