"""Waking the Shield over ADB, with a fake adb standing in for the box."""
import pytest

from muthur.shield import Shield, ShieldError

APPS = """3 activities found:
  Activity #0:
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    com.android.tv.settings/.MainSettings
  Activity #1:
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    org.xbmc.kodi/.Splash
  Activity #2:
    com.google.android.youtube.tv/com.google.android.apps.youtube.tv.activity.ShellActivity"""


class FakeAdb:
    def __init__(self, state="device", awake=False):
        self.state, self.awake, self.calls = state, awake, []

    def __call__(self, args, home, timeout):
        self.calls.append(" ".join(args))
        if args[0] == "connect":
            return 0, "connected"
        if args[0] == "devices":
            return 0, f"List of devices attached\nbox:5555\t{self.state}\n"
        cmd = args[-1]
        if cmd.startswith("cmd package query-activities"):
            return 0, APPS
        if cmd == "dumpsys power":
            return 0, f"mWakefulness={'Awake' if self.awake else 'Asleep'}"
        if cmd == "dumpsys activity activities":
            return 0, "  topResumedActivity=ActivityRecord{1 u0 org.xbmc.kodi/.Splash t12}"
        if cmd == "input keyevent KEYCODE_WAKEUP":
            self.awake = True
        return 0, ""


def test_apps_and_the_one_on_screen_come_from_the_box():
    s = Shield("box", 5555, "/cfg", FakeAdb())
    assert s.apps() == ["com.android.tv.settings/.MainSettings", "com.google.android.youtube.tv/com.google.android.apps.youtube.tv.activity.ShellActivity",
                        "org.xbmc.kodi/.Splash"]
    assert s.current_app() == "org.xbmc.kodi"


def test_wake_starts_the_app_and_waits_until_it_answers():
    adb, answers = FakeAdb(awake=False), iter([False, False, True])
    result = Shield("box", 5555, "/cfg", adb).wake_and_start("org.xbmc.kodi/.Splash", lambda: next(answers), wait=10)
    assert result == {"ok": True, "woke": True}
    shell = [c for c in adb.calls if " shell " in c]
    assert shell == ["-s box:5555 shell dumpsys power", "-s box:5555 shell input keyevent KEYCODE_WAKEUP", "-s box:5555 shell am start -n org.xbmc.kodi/.Splash"]


def test_an_awake_box_only_gets_the_app_started():
    adb = FakeAdb(awake=True)
    assert Shield("box", 5555, "/cfg", adb).wake_and_start("org.xbmc.kodi/.Splash", lambda: True)["woke"] is False
    assert not any("KEYCODE_WAKEUP" in c for c in adb.calls)


@pytest.mark.parametrize("state,words", [("unauthorized", "Always allow"), ("offline", "network debugging on")])
def test_the_reader_is_told_what_to_do(state, words):
    with pytest.raises(ShieldError, match=words):
        Shield("box", 5555, "/cfg", FakeAdb(state=state)).connect()
