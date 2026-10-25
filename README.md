# muthur

Sorts finished downloads into a Kodi library and writes Kodi-native `.nfo` files and artwork next to them, so Kodi never has to scrape online.

It's built for a Synology NAS running Container Manager, with Kodi reading the library over SMB, but nothing in it is Synology-specific apart from the Download Station integration.

**Status:** version 0.9. muthur checks the downloads folder, shows what each download is and where it goes, and on your go-ahead moves ready ones into the library with Kodi NFOs and artwork. What it isn't sure about waits in Review, where you pick the show, film or episode (including shows your library numbers differently from TMDB), and it asks Kodi to scan after every run. NFOs it writes carry IMDb's score (from IMDb's weekly datasets) as the one Kodi shows. It keeps an hourly backup of what you watched in Kodi, which survives renames and a lost Kodi database, and can restore it. The Library page shows every show, episode and film with its score, watched status and what is wrong with it. Duplicates proposes which copy of an episode or film to keep, by measured quality, and carries the watched status over when you confirm. Health lists what's wrong in the library and makes the fixes it can make without guessing, such as adding IMDb scores to existing NFOs, in batches you approve. Every change is journalled and a run can be put back from History. It flags programs disguised as episodes and never touches them, never overwrites a file, and learns the shows already in the library.

## What it will do
- Identify movies and episodes from file and folder names (via [guessit](https://github.com/guessit-io/guessit) plus its own rules), using TMDB.
- Remember every confirmed show and movie by ID, so later downloads never get re-guessed.
- Send anything ambiguous (a title without a year shared by two films, an episode that doesn't exist) to a review queue instead of guessing.
- Write Kodi NFOs with IMDb scores per episode, from IMDb's free non-commercial datasets.
- Pick the best copy among duplicates, move the rest to a quarantine folder, and keep a journal with undo.

The architecture is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and the look and UI rules in [DESIGN.md](DESIGN.md).

## Running it

On a Synology NAS: see [docs/DEPLOY.md](docs/DEPLOY.md). Locally, for development:

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"           # Windows; use .venv/bin/pip elsewhere
cd web && npm ci && npm run build && cd ..
.venv/Scripts/python scripts/dev.py              # http://127.0.0.1:8580, settings from .env
```

## Command-line dry run

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
