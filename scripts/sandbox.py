"""Run muthur against local/sandbox (git-ignored) on http://127.0.0.1:8590, for testing Apply and Undo safely."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sb = root / "local" / "sandbox"
os.environ.update({
    "MUTHUR_CONFIG": str(sb / "config"), "MUTHUR_DOWNLOADS": str(sb / "complete"), "MUTHUR_TV": str(sb / "TV"),
    "MUTHUR_FILM": str(sb / "Film"), "MUTHUR_QUARANTINE": str(sb / "_muthur-quarantine"),
})
os.chdir(root)
sys.path.insert(0, str(root / "src"))
import uvicorn  # noqa: E402

uvicorn.run("muthur.web:get_app", factory=True, host="127.0.0.1", port=8590, workers=1)
