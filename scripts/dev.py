"""Run muthur locally for development: the API plus the built UI on http://127.0.0.1:8580.

Settings come from .env in the repository root (git-ignored), for example:
    MUTHUR_CONFIG=local/config
    MUTHUR_DOWNLOADS=//nas/share/torrent-output/complete
"""
import os
import sys
from pathlib import Path

import uvicorn

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "src"))
uvicorn.run("muthur.web:get_app", factory=True, host="127.0.0.1", port=int(os.environ.get("PORT", 8580)), workers=1)
