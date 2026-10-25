"""Wake the Android TV box (the Shield) and start the media app over ADB (network debugging).

Nothing about the box or the app is built in: the address is Kodi's, the port and the app are
settings, and the app list and its launch activity come from the box itself. The box approves
muthur's own ADB key once, on the TV; the key lives in muthur's config folder.

Tested on the Shield 2019 (2026-10-25): over ADB it wakes from sleep and starts Kodi every time;
the Android TV Remote protocol did neither (ARCHITECTURE.md §11).
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time

COMPONENT = re.compile(r"^\s*([A-Za-z][\w.]*/[\w.$]+)\s*$")


class ShieldError(Exception):
    """A sentence for the reader."""


def run_adb(args: list[str], home: str, timeout: float = 20) -> tuple[int, str]:
    """adb with its key in `home`/.android (muthur's config folder, so the approval survives updates)."""
    if not shutil.which("adb"):
        raise ShieldError("adb isn't installed in muthur's container.")
    try:
        p = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout, env={**os.environ, "HOME": home})
    except subprocess.TimeoutExpired:
        return 1, "timed out"
    return p.returncode, (p.stdout + p.stderr).strip()


class Shield:
    def __init__(self, host: str, port: int, home: str, runner=run_adb):
        self.serial, self.home, self.runner = f"{host}:{port}", home, runner

    def _adb(self, *args: str, timeout: float = 20) -> str:
        code, out = self.runner(list(args), self.home, timeout)
        if code != 0:
            raise ShieldError(f"adb failed: {out[:200]}")
        return out

    def _shell(self, command: str, timeout: float = 20) -> str:
        return self._adb("-s", self.serial, "shell", command, timeout=timeout)

    def connect(self) -> str:
        """'device' when muthur may use the box; otherwise a ShieldError that says what to do."""
        self.runner(["connect", self.serial], self.home, 15)
        out = self._adb("devices")
        state = next((line.split()[1] for line in out.splitlines() if line.startswith(self.serial + "\t") or line.startswith(self.serial + " ")), None)
        if state == "device":
            return state
        if state == "unauthorized":
            raise ShieldError("The TV asks to allow network debugging for muthur: tick 'Always allow' and press OK, then try again.")
        raise ShieldError(f"Nothing answers at {self.serial}. Is network debugging on (Device Preferences, Developer options)?")

    def apps(self) -> list[str]:
        """The apps the box can start from its home screen, as package/activity."""
        out = self._shell("cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.LEANBACK_LAUNCHER")
        return sorted({m.group(1) for line in out.splitlines() if (m := COMPONENT.match(line))})

    def current_app(self) -> str | None:
        """The package of the app on screen right now."""
        out = self._shell("dumpsys activity activities")
        m = re.search(r"(?:topResumedActivity|mResumedActivity)[^\n]*?\s([\w.]+)/", out)
        return m.group(1) if m else None

    def awake(self) -> bool:
        return "mWakefulness=Awake" in self._shell("dumpsys power")

    def wake_and_start(self, component: str, ready, wait: float = 60) -> dict:
        """Wake the box, start `component`, and wait until ready() is true (the app answers)."""
        if not COMPONENT.match(component):  # it ends up in a shell command on the box
            raise ShieldError("The app in Settings isn't one from the Shield's list. Choose it again.")
        self.connect()
        woke = False
        if not self.awake():
            self._shell("input keyevent KEYCODE_WAKEUP")
            woke = True
        self._shell(f"am start -n {shlex.quote(component.strip())}")
        end = time.time() + wait
        while time.time() < end:
            if ready():
                return {"ok": True, "woke": woke}
            time.sleep(2)
        raise ShieldError(f"The box is awake and {component.split('/')[0]} was started, but it didn't answer within {int(wait)} seconds.")
