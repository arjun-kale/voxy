from __future__ import annotations

import shutil
import subprocess


class DesktopNotifier:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._binary = shutil.which("notify-send") if enabled else None

    def show(self, title: str, body: str) -> None:
        if not self._binary:
            return
        subprocess.Popen(
            [self._binary, "--app-name=Voxy", "--icon=audio-input-microphone", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
