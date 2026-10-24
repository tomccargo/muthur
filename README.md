# muthur

Sorts finished downloads into a Kodi library and writes Kodi-native `.nfo` files and artwork next to them, so Kodi never has to scrape online.

It's built for a Synology NAS running Container Manager, with Kodi reading the library over SMB, but nothing in it is Synology-specific apart from the Download Station integration.

**Status:** early. Milestone 1 is a **read-only** command-line dry run. It parses and identifies an existing library and reports how its matches compare with the IDs already in the library's NFO files. It never writes to the library.

## What it will do
- Identify movies and episodes from file and folder names (via [guessit](https://github.com/guessit-io/guessit) plus its own rules), using TMDB.
- Remember every confirmed show and movie by ID, so later downloads never get re-guessed.
- Send anything ambiguous (a title without a year shared by two films, an episode that doesn't exist) to a review queue instead of guessing.
- Write Kodi NFOs with IMDb scores per episode, from IMDb's free non-commercial datasets.
- Pick the best copy among duplicates, move the rest to a quarantine folder, and keep a journal with undo.

The full design is in [docs/DESIGN.md](docs/DESIGN.md).

## Milestone 1: dry run

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Windows; use .venv/bin/pip elsewhere
cp .env.example .env                      # add your TMDB read access token
.venv/Scripts/muthur dryrun --tv "\\\\nas\\share\\TV" --film "\\\\nas\\share\\Film" --out reports
```

Reports are written to `reports/`, which is git-ignored because they list your library's contents.

## Data sources
- [TMDB](https://www.themoviedb.org/): this product uses the TMDB API but is not endorsed or certified by TMDB.
- [IMDb non-commercial datasets](https://developer.imdb.com/non-commercial-datasets/): personal, non-commercial use only.

## Licence
MIT. The dependency guessit is LGPL-3.0 and is used unmodified.
