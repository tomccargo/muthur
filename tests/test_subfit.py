"""Subtitle files that don't fit their video (subfit): measured against the subtitles inside it, stretched when only
the speed or a shift is off (Dune's YTS file: 25 fps against 23.976, six minutes off by the end)."""
from muthur import subfit
from test_health import env, write  # noqa: F401  (the Health fixture)

LINES = [f"this is line number {n} of the film" for n in range(400)]


def srt(times: list[float]) -> str:
    def stamp(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "".join(f"{i + 1}\n{stamp(t)} --> {stamp(t + 2)}\n{LINES[i]}\n\n" for i, t in enumerate(times))


VIDEO = [20.0 * i + 5 for i in range(400)]  # one line every 20 s: where the video says them
# Three windows as sample() reads them: lines at 20%, 50% and 80% of an 8000 s film, five minutes each.
REFERENCE = [(t, subfit._words([LINES[i]])) for i, t in enumerate(VIDEO) if any(s * 8000 <= t < s * 8000 + 300 for s in subfit.WINDOWS)]


def measured(times):
    return subfit.fit(REFERENCE, subfit.cues(srt(times)))


def test_a_file_that_fits():
    f = measured(VIDEO)
    assert subfit.verdict(f) == "fits" and abs(f["shift"]) < 0.01 and abs(f["speed"] - 1) < 1e-6


def test_a_file_made_for_25_fps_is_stretched():
    pal = [t * 24000 / 1001 / 25 for t in VIDEO]  # runs 4.3% fast, like Dune's YTS file
    f = measured(pal)
    assert subfit.verdict(f) == "stretch" and abs(f["speed"] - 25 * 1001 / 24000) < 1e-4
    assert subfit.describe(f) == "4.3% too fast"
    fixed = subfit.cues(subfit.retime(srt(pal).encode(), f["shift"], f["speed"]).decode())
    assert max(abs(t - VIDEO[i]) for i, (t, _) in enumerate(fixed)) < 0.05  # back where the video says them


def test_a_shifted_file_is_moved_and_a_cut_one_left_alone():
    f = measured([t - 3.5 for t in VIDEO])  # an intro cut differently
    assert subfit.verdict(f) == "stretch" and abs(f["shift"] - 3.5) < 0.01 and subfit.describe(f) == "3.5 s too early"
    jumbled = [VIDEO[i] + (0 if i < 200 else 90) for i in range(400)]  # a scene added halfway: no one line fits it
    assert subfit.verdict(measured(jumbled)) == "cut"
    assert subfit.fit(REFERENCE, subfit.cues(srt(VIDEO[:3]))) is None  # too few lines in common: can't tell


def test_health_stretches_the_file_and_history_can_put_it_back(env):  # noqa: F811
    tmp, health, _ = env
    path = "Film/Solaris (1972)/Solaris (1972).en.srt"
    pal = srt([t * 24000 / 1001 / 25 for t in VIDEO[:20]])
    write(tmp / path, pal)
    x = {"path": path, "shift": 0.0, "speed": 25 * 1001 / 24000, "why": "4.3% too fast"}
    result = health.apply({"fixes": {"subtitle-timing": [x]}}, ["subtitle-timing"])
    assert result["failed"] == [] and result["done"]["subtitle-timing"] == 1
    fixed = subfit.cues((tmp / path).read_text(encoding="utf-8"))
    assert abs(fixed[10][0] - VIDEO[10]) < 0.05
    assert any(p.name == "Solaris (1972).en.srt" for p in (tmp / "_q").rglob("*.srt"))  # the original, in quarantine
    health.journal.undo(result["run"])
    assert (tmp / path).read_text(encoding="utf-8") == pal
