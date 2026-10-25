"""Facts read from media files themselves."""
from __future__ import annotations

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
