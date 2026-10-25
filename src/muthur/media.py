"""Facts read from media files themselves."""
from __future__ import annotations

import json
import shutil
import subprocess


def probe_duration(path: str | None) -> int | None:
    """Duration in seconds from the file header via ffprobe (reads only the start of the file)."""
    if not path or not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return int(float(out)) if out else None
    except (subprocess.SubprocessError, ValueError):
        return None


def probe(path: str) -> dict | None:
    """What a video really is, from its headers: duration, the main video stream and the best
    audio stream. None when ffprobe is missing or can't read the file."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration:stream=codec_type,codec_name,profile,width,height,channels,color_transfer:stream_tags=language",
                              "-of", "json", path], capture_output=True, text=True, timeout=120).stdout
        data = json.loads(out or "{}")
    except (subprocess.SubprocessError, ValueError):
        return None
    streams = data.get("streams") or []
    video = [x for x in streams if x.get("codec_type") == "video" and x.get("codec_name") not in ("mjpeg", "png", "bmp")]
    audio = [x for x in streams if x.get("codec_type") == "audio"]
    if not video:
        return None
    v = max(video, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
    a = max(audio, key=lambda x: x.get("channels") or 0) if audio else {}
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {"width": v.get("width") or 0, "height": v.get("height") or 0, "vcodec": v.get("codec_name"),
            "hdr": v.get("color_transfer") in ("smpte2084", "arib-std-b67"),
            "acodec": a.get("codec_name"), "aprofile": a.get("profile"), "channels": a.get("channels") or 0,
            "duration": duration, "subtitles": sum(1 for x in streams if x.get("codec_type") == "subtitle")}
