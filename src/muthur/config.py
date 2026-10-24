"""Settings from the environment, with a minimal .env loader."""
import os


def load_dotenv(path: str = ".env") -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def tmdb_token() -> str:
    token = os.environ.get("TMDB_READ_TOKEN", "").strip()
    if not token:
        raise SystemExit("TMDB_READ_TOKEN is not set. Copy .env.example to .env and add your TMDB read access token.")
    return token
