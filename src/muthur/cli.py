"""Command line: `muthur dryrun ...` and `muthur parse ...`."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from .config import load_dotenv, tmdb_token
from .parse import parse_episode, parse_movie


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="muthur")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dryrun", help="read-only: identify an existing library and compare with its NFO IDs")
    d.add_argument("--tv", help="TV library root")
    d.add_argument("--film", help="Film library root")
    d.add_argument("--out", default="reports")
    d.add_argument("--cache", default=".cache")
    d.add_argument("--rescan", action="store_true", help="walk the library again instead of using the cached scan")
    d.add_argument("--limit", type=int, help="only the first N shows/movies (for quick tests)")
    d.add_argument("--workers", type=int, default=8)

    p = sub.add_parser("parse", help="show how a path is parsed")
    p.add_argument("kind", choices=["episode", "movie"])
    p.add_argument("path", help="path relative to the library root, e.g. 'Show/Season 01/file.mkv'")

    args = ap.parse_args(argv)
    if args.cmd == "parse":
        parts = args.path.replace("\\", "/").split("/")
        res = parse_episode(parts) if args.kind == "episode" else parse_movie(parts)
        print(json.dumps(asdict(res), indent=2, ensure_ascii=False, default=str))
        return

    load_dotenv()
    from .dryrun import run
    from .tmdb import Tmdb

    if not (args.tv or args.film):
        ap.error("give --tv and/or --film")
    tmdb = Tmdb(tmdb_token(), os.path.join(args.cache, "tmdb.sqlite"))
    out = run(tmdb, args.tv, args.film, args.out, args.cache, args.rescan, args.limit, args.workers)
    print(f"Report: {os.path.join(out, 'summary.md')}")


if __name__ == "__main__":
    main()
