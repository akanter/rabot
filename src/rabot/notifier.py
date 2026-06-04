import subprocess


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
