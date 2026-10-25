# muthur — architecture

**muthur** (MU/TH/UR, "Mother", the Nostromo's computer) is the project name. The Python package and CLI are called `muthur`.

Status: 2026-10-25. Milestones 1 (dry run), 2 (container, web UI, inbox) and 3 (Apply with journal and undo, Kodi NFOs and artwork, Review) are done. Milestone 4 (IMDb scores §8, watched-status backup §11) is done. Kodi on the Shield is set up as in §10. The look and the UI rules are in [`../DESIGN.md`](../DESIGN.md).

## 1. Goal

A self-hosted web app on the Synology NAS **Nostromo** that:

1. picks up finished downloads from `torrent-output`,
2. works out exactly which movie, show or episode each file is, and asks when it isn't sure,
3. moves and renames it into `TV` or `Film`,
4. writes Kodi-native `.nfo` files and artwork next to it, including **per-episode IMDb scores**,

so that Kodi on the Shield never has to scrape online. Kodi only reads what is on disk.

It also manages the existing library: a health report, duplicates, fixing wrong matches, and a weekly score refresh.

### Non-goals
- No searching, indexers or download automation. It never talks to a tracker.
- No "monitoring" of shows the way Sonarr does.
- No transcoding or editing of media files.

## 2. Environment

| Item | Value |
|---|---|
| NAS | Synology DS918+ (Intel Celeron J3455, x86-64), DSM 7.2, Container Manager |
| Shares | `\\nostromo\Iedereen\torrent-output` (`complete/`, `incomplete/`), `\TV`, `\Film` — all on the same share |
| Player | Kodi 21.x on an NVIDIA Shield (2019), library over SMB |
| Library size (Oct 2026) | 197 show folders / 4,949 episodes, about 660 movies |

## 3. Architecture

One container, one process, one SQLite file.

```
┌──────────────────────── container "muthur" ──────────────────────────┐
│  Web UI (React + TypeScript, built with Vite, served as static files) │
│        │  REST + server-sent events (live job progress)               │
│  API (Python 3.12, FastAPI)                                           │
│        │                                                              │
│  Job runner (in-process queue: scan, identify, apply, refresh)        │
│   ├─ Parser ........ guessit + own rules (anime, "EP 1", "101")       │
│   ├─ Identifier .... TMDB API, ID memory, scoring                     │
│   ├─ Ratings ....... IMDb datasets (local), TMDB                      │
│   ├─ Planner ....... target paths, NFO, artwork, duplicates           │
│   ├─ Executor ...... moves with journal and undo                      │
│   └─ Kodi client ... JSON-RPC to the Shield (scan, refresh)           │
│  SQLite (/config/muthur.db), artwork cache, IMDb cache, logs        │
└──────────────────────────────────────────────────────────────────────┘
```

**Why this stack:** Python has the best filename parser ([guessit](https://pypi.org/project/guessit/), actively maintained, 4.4.0 released July 2026) and simple TMDB/XML handling. React gives the rich UI you asked for (drag and drop, inline editing, keyboard review). SQLite needs no extra database container. A multi-stage Dockerfile builds the frontend and ships one image.

### Resource guardrails (DS918+: Celeron J3455, 4 GB)

Measured on 2026-10-25: the whole backend (Python, FastAPI, uvicorn, guessit, muthur) uses **about 72 MB** after parsing 4,919 episode names. guessit takes ~15 ms per name on a Ryzen 7 3700X (PassMark single-thread 2,655), so about **50 ms on the J3455** (812, about 3.3× slower). That is ~1 s for a day's downloads and ~4 min for a full library check.

- **Memory cap:** the container runs with `mem_limit: 256m`, so it can never squeeze DSM, Download Station or SMB.
- **CPU:** `cpu_shares` lower than the default, and long jobs (library check, ID-memory import, score refresh) run in a thread at nice 10. Interactive requests stay at normal priority.
- **Parse once:** every parsed name is cached in SQLite, keyed by the name and the parser version. A full library check is slow only the first time and after a parser update.
- **SQLite in WAL mode with `synchronous=NORMAL`.** Measured on the NAS's disks: 813 ms per commit in SQLite's default mode, 0.1 ms in WAL. With a commit per cached name, the default mode made the first library import take over an hour.
- **One process, one worker.** No worker pool, no in-memory copy of the library; lists are paged from SQLite.

Rewriting the backend in Go would use less memory but would lose guessit, the most accurate parser available. That isn't worth it at these numbers.

### Volumes — one mount, on purpose
```yaml
volumes:
  - /volume1/Iedereen:/data        # torrent-output, TV, Film, quarantine
  - /volume1/docker/muthur:/config
```
`torrent-output`, `TV` and `Film` **must be under one bind mount**. Moving a file between two separate Docker bind mounts can't be a simple rename, even on the same disk. Docker falls back to copy-then-delete, which is slow and not atomic. With one mount, a move is an instant rename.

- The container runs as a dedicated DSM user (PUID/PGID) with read/write on `Iedereen` only.
- The web UI is on the LAN only (for example `http://nostromo:8580`), with an optional password.
- `quarantine` lives at `/data/_muthur-quarantine`.

## 4. Data sources

| Source | Used for | Cost / terms |
|---|---|---|
| **TMDB API** | Identification, titles, plots, cast, artwork, TMDB scores, season/episode structure, specials, anime episode groups | Free for non-commercial use with attribution ([TMDB FAQ](https://developer.themoviedb.org/docs/faq)). Needs your own API key. The UI shows "Data from TMDB". |
| **IMDb datasets** | IMDb scores for movies, shows **and episodes** | Free daily files for personal, non-commercial use ([IMDb](https://developer.imdb.com/non-commercial-datasets/)). Uses `title.episode` and `title.ratings`. |
| Existing NFOs | ID memory: 179 shows already have TVDB/TMDB/IMDb IDs | Read once at import |
| fanart.tv (optional) | `clearlogo.png`, `landscape.jpg`, `banner.jpg` | Free personal API key |
| TVDB | Not queried. Existing TVDB IDs stay in the NFOs as a second `uniqueid`. | — |

## 5. The pipeline

```
Scan → Parse → Identify → Plan → (Review) → Apply → Tell Kodi
```

### 5.1 Scan
- Only `torrent-output/complete/` is scanned (`incomplete/` never).
- An item is ready when its size and modification time haven't changed for 10 minutes.
- Each torrent folder or loose file is one **item**. Its files are sorted into video, subtitle, scene NFO, sample, junk and other.
- **Anything that isn't video** (games, archives, ISOs of software, comics) is marked *Ignored* with a reason. It is never touched, and the user can hide it.

### 5.2 Parse
guessit plus own rules for patterns guessit gets wrong or doesn't cover:
- anime absolute numbering `[Group] Show - 01 [720p]`, `EP 1`, `Show 12`
- `101.mkv` (season 1, episode 01), only when the folder context says it's a show
- `part01` → episode 1 of a single season
- site-name prefixes and tags (`www.example.org - …`, `[site]`) stripped
- scene `.nfo` contents scanned for an `imdb.com/title/tt…` link (a strong signal)

### 5.3 Identify
In order, stopping at the first conclusive step:

1. **ID memory.** If the parsed show title maps to a show already in the library (alias table, filled from the existing NFOs and every confirmed match), use its stored TMDB ID. No search. This is what puts a new *Ghosts* episode in *Ghosts (2021)*, never in *Ghosts (2019, UK)*.
2. **Explicit ID** in a scene NFO (IMDb `tt…`) → TMDB `find` by external ID.
3. **TMDB search** (movie or TV, by parsed type) → up to 10 candidates → scored.

**Score signals (0–1 each, weighted):**

| Signal | Notes |
|---|---|
| Title similarity | Normalised; checked against original, English and alternative titles |
| Year | Exact = full, ±1 = partial, missing = neutral (not positive) |
| Episode exists | Does SxxEyy exist on that show in TMDB? Hard fail if not. |
| Runtime fits | ffprobe duration vs TMDB runtime, ±15 % |
| Language | Original language vs audio track languages |
| Popularity | Small tie-breaker only |

**Auto-accept only when all hold:**
- best score ≥ 0.90, **and**
- the gap to the runner-up ≥ 0.15, **and**
- no other candidate has the same normalised title unless the year settles it, **and**
- for episodes: the episode exists.

Anything else goes to **Review**, with the candidates shown (poster, year, plot, why they scored). This covers the *Inside Job* case (2010 documentary vs 2021 series) and the "1970 vs 2002" case. A guess is never made silently.

**Episode numbering that differs from TMDB.** Some libraries and releases number a show differently from TMDB: *The Office* (US) season 4 has 19 split episodes in the library and in releases, and 14 hour-long ones on TMDB. None of TMDB's episode groups for that show uses the split order (checked 2026-10-25), so muthur maps per file instead:
- When a file's number doesn't exist on TMDB, or the episode title in its name matches a *different* TMDB episode than the one at its number (S04E10 *Branch Wars* vs TMDB's S04E10 *Chair Model*), the item goes to Review with the matching TMDB episode suggested (title similarity ≥ 0.85, "Part 2" ignored).
- In Review you pick the TMDB episode and the part. By default the file **keeps its own number**, so the season folder stays consistent; the NFO gets that TMDB episode's plot, date, score and ID under the file's number and title (*Goodbye Toby (2)*, S04E19).
- A number already used in the library's season folder, under any file name, is refused: Kodi would list two S04E14s.

### 5.4 Plan
For each identified item: target path, the NFOs to write, the artwork to download, and conflicts.

- **Target exists?** That's a duplicate. Both versions get a quality score, the better one is proposed as the winner, and the user confirms (see §9).
- **Subtitles** follow their video: `.en.srt`, `.nl.srt`, `.en.forced.srt`.
- **Junk** (tracker `.txt`, `.exe`, samples, `.part`, `Screens/`) is not copied. When a torrent folder holds only junk after the move, the folder goes to quarantine.

### 5.5 Apply
- Every operation is written to a **journal** first (from, to, hash of the first and last 1 MB, timestamp), then executed.
- **Undo** replays the journal in reverse, per item or per run.
- Never overwrite, never delete: anything that would be lost goes to quarantine.
- **Dry run** is a global switch. Everything up to Apply runs and the plan is shown, but nothing is written.

### 5.6 Tell Kodi
Kodi JSON-RPC on the Shield (Settings → Services → Control → *Allow remote control via HTTP*):
- after Apply: `VideoLibrary.Scan` with `directory` set to only the changed show or movie folder ([forum example](https://forum.kodi.tv/showthread.php?tid=227491)), not a full library scan.
- after a score refresh: update the changed items. The exact method (refresh vs `Set*Details`) gets verified with `JSONRPC.Introspect` on the Shield during the prototype.

## 6. Naming

Kodi takes season and episode only from the filename, not the NFO ([Kodi wiki](https://kodi.wiki/view/Naming_video_files/Episodes)), so the filename must always carry `SxxEyy`.

### TV
```
TV/
  Foundation (2021)/
    tvshow.nfo  poster.jpg  fanart.jpg  clearlogo.png  banner.jpg
    season01-poster.jpg  season-specials-poster.jpg
    Season 01/
      Foundation (2021) - S01E01 - The Emperor's Peace.mkv
      Foundation (2021) - S01E01 - The Emperor's Peace.nfo
      Foundation (2021) - S01E01 - The Emperor's Peace-thumb.jpg
      Foundation (2021) - S01E01 - The Emperor's Peace.en.srt
    Specials/
      Foundation (2021) - S00E01 - ….mkv
    Extras/            ← bonus material not in TMDB, excluded from the library
```
- Show folders **always get a year**. It costs nothing and prevents same-name collisions.
- Multi-episode files: `S01E01-E02`.
- Specials: `S00Exx`, numbered as in TMDB's season 0.
- **Anime:** absolute numbers are mapped to TMDB seasons using the episode count per season, or a TMDB "absolute" episode group when one exists. If the counts don't add up, the item goes to Review. Short series (Death Note, Psycho-Pass, Tokyo Ghoul, Magi) map one to one.

### Film
```
Film/
  Aguirre, der Zorn Gottes (1972)/
    Aguirre, der Zorn Gottes (1972).mkv
    Aguirre, der Zorn Gottes (1972).nfo
    poster.jpg  fanart.jpg  clearlogo.png
    Aguirre, der Zorn Gottes (1972).en.srt
    Extras/
      Making of.mkv
```
- Always one movie per folder. The 41 loose movies in the root get folders.
- `Extras/` uses Kodi's video extras feature (v21+, needs movie folders). It also needs the `advancedsettings.xml` exclusion in §10 so extras aren't listed as movies ([Kodi wiki: Video extras](https://kodi.wiki/view/Video_extras)).
- Discs split into parts: `… (2004) - cd1.avi`, `- cd2.avi` (Kodi stacks these).

### Title rule
- Plots, taglines and genres: **English** (`en-US`).
- Title: **original title** when the original language uses Latin script (fr, de, it, nl, es, pt, sv, da, no, fi, pl, cs, …). English title for Japanese, Korean, Chinese and other non-Latin scripts.
- `<originaltitle>` always holds the original. Every item can be overridden in the UI.
- Illegal filename characters (`: ? * " < > |`) are replaced; `:` becomes ` -`.

## 7. NFO content

Formats per the Kodi wiki ([movies](https://kodi.wiki/view/NFO_files/Movies), [TV shows](https://kodi.wiki/view/NFO_files/TV_shows), [episodes](https://kodi.wiki/view/NFO_files/Episodes)).

**Ratings block (movies, shows and episodes):**
```xml
<ratings>
  <rating name="imdb" max="10" default="true"><value>8.7</value><votes>41233</votes></rating>
  <rating name="themoviedb" max="10"><value>8.1</value><votes>512</votes></rating>
</ratings>
<uniqueid type="tmdb" default="true">93740</uniqueid>
<uniqueid type="imdb">tt0804484</uniqueid>
<uniqueid type="tvdb">366972</uniqueid>
```

| NFO | Main fields |
|---|---|
| movie | title, originaltitle, sorttitle, year, premiered, plot, tagline, runtime, genre, country, studio, director, credits, actor (top 15), set, ratings, uniqueid |
| tvshow | title, originaltitle, year, premiered, status, plot, studio, genre, actor, namedseason, ratings, uniqueid |
| episode | title, showtitle, season, episode, aired, plot, runtime, director, credits, ratings, uniqueid |

Each NFO carries a comment `<!-- muthur vX, tmdb:93740, 2026-10-24 -->` so the tool recognises its own files.

## 8. Scores

- **IMDb is the score Kodi shows** (`default="true"`), with TMDB stored as a second score.
- IMDb datasets are downloaded weekly (`title.ratings.tsv.gz`, `title.episode.tsv.gz`). Only the rows for titles in the library are kept in SQLite.
- **Episode mapping:** show IMDb ID (from TMDB `external_ids`) + season + episode → `title.episode` → the episode's `tt` ID → `title.ratings`.
- **Sanity check:** per season, IMDb and TMDB episode counts are compared. If they differ (common for anime, double episodes, specials), IMDb scores for that season are left out and TMDB becomes the default there. The UI shows this.
- **Weekly refresh:** scores are recomputed. An NFO is only rewritten when a value changed by ≥ 0.1 or the votes changed by ≥ 10 %, then Kodi is told to refresh that item.

**As built (0.5, 2026-10-25):**
- The datasets are IMDb's [non-commercial datasets](https://data.imdb.com/non-commercial-datasets/), for personal, non-commercial use. Both files (about 64 MB together) are streamed and filtered line by line, so memory stays small; on the PC a full refresh took 10 s.
- Which shows: every folder in `TV/`. Its IMDb ID comes from `tvshow.nfo`, or, for NFOs without one (Sonarr writes TVDB IDs), through the TMDB ID in the NFO or in muthur's show memory and TMDB's external IDs. Films: the IMDb IDs in the films' NFOs.
- New NFOs get IMDb as `default="true"` and TMDB second. An episode filed under another number than TMDB's (Review's numbering choice, §5.3) gets no IMDb score, because nothing in the datasets confirms which IMDb episode it is.
- The weekly refresh (and *Refresh scores now* on the Dashboard) only rewrites NFOs **muthur wrote**: found through the journal's `write` operations and still carrying muthur's comment. Each rewrite is journalled as an `update` with a copy of the old file in `/config/backups/<run>/`, so a refresh run can be put back from History. NFOs from other tools wait for phase 3.
- An episode NFO is checked against TMDB before its score changes: the TMDB episode at the NFO's number must be the one in its `uniqueid`, or it is left alone.

## 9. Duplicates and quality

**Quality score**, highest first:
1. Source: Blu-ray remux > Blu-ray > WEB-DL > WEBRip > HDTV > DVD > TV/telesync
2. Resolution: 2160p > 1080p > 720p > SD
3. HDR: no bonus (the TV is SDR; setting can change this later)
4. Video codec: AV1 ≈ HEVC > H.264 > older
5. Audio: lossless/Atmos > 5.1 > stereo
6. Bitrate per minute (a tiebreaker against over-compressed encodes)
7. Subtitles present (en/nl)

The tool proposes a winner and you confirm. The loser goes to `_muthur-quarantine/<date>/…` with a small JSON note on why. The quarantine can be emptied from the UI, per item or everything older than N days.

## 10. Kodi setup (one-time, on the Shield)

Done on 2026-10-25 (Kodi 21.2), through Kodi's JSON-RPC from muthur's side; the state is noted per step.

1. For both sources (`TV` and `Film`): **Change content → Information provider → "Local information only"**, answering **No** to *refresh information for all items*. Items without an NFO are then not scraped at all ([Kodi wiki: NFO files](https://kodi.wiki/view/NFO_files)). The tool makes sure every item it files has one. *Done.*
2. The downloads source (`torrent-output`): **Change content → None**, answering **Yes** to *remove all items within this path*. Kodi had scraped downloads into the library itself (the `complete` folder as a show called *Complete Savages*). *Done: 6 stray shows and 15 episodes removed, none watched. Dark Winds lost its 7 episodes because its show entry pointed at the downloads; a scan brought them back from their NFOs.*
3. Film source: "Movies are in separate folders that match the movie title" stays **off** as it was; muthur puts every film in its own folder either way, and the NFO next to the video wins.
4. *Not set, not needed while muthur files no Extras:* `advancedsettings.xml` to keep Extras out of the library, per the [Add-on:Extras](https://kodi.wiki/view/Add-on:Extras) example:
   ```xml
   <advancedsettings>
     <video>
       <excludefromscan action="append"><regexp>[\\/]extras[\\/]</regexp></excludefromscan>
       <excludetvshowsfromscan action="append"><regexp>[\\/]extras[\\/]</regexp></excludetvshowsfromscan>
     </video>
   </advancedsettings>
   ```
5. *Allow remote control via HTTP* with a username and password, entered in muthur's settings. *Done; muthur asks Kodi to scan after every Apply.*
6. Left as they are: *date added* uses the file's modification date (Kodi's default `<dateadded>1`), so filed episodes sort by their own date in *Recently added*; *Update library on startup* and background updates are off; library *Export* to separate files would overwrite muthur's NFOs and isn't used.

## 11. Watched status: Kodi is the master, muthur keeps a synced backup

Kodi stores play count, last played and resume point in its own database on the Shield, **per file path**. That database has been lost before, and renaming a file makes Kodi treat it as new and unwatched. So muthur keeps a continuously updated backup, keyed by what the item *is* rather than where it lives.

**Roles**
- **Kodi is the master.** Whatever Kodi says is the truth, including when you mark something unwatched.
- **muthur is a backup that follows Kodi**, in one direction (Kodi → muthur), all the time.
- **muthur writes to Kodi only in two explicit cases:**
  1. after muthur itself renamed or moved files, to carry each item's status to its new path, and
  2. when you press **Restore** (after a Kodi reinstall or a lost database), after a preview of what will change.

  It never writes to Kodi on its own initiative otherwise. So this is a backup with restore, not two-way sync, which avoids most of what makes sync dangerous.

**How the backup follows Kodi**
- Listens to Kodi's JSON-RPC notifications over WebSocket (port 9090: `VideoLibrary.OnUpdate` carries the new play count) for near-instant updates ([forum example](https://forum.kodi.tv/showthread.php?tid=197858)).
- Polls a full snapshot (`VideoLibrary.GetMovies` / `GetEpisodes` with `playcount`, `lastplayed`, `resume`, `uniqueid`, `file`) every hour and when muthur starts, because notifications don't fire for every change (for example changes made by add-ons) and the Shield may be off.
- Each record is keyed by **TMDB ID** (movies) or **show TMDB ID + season + episode** (episodes), with IMDb/TVDB IDs and the last known path alongside. A key that survives renames, moves and reinstalls.

**Safety rules** (where sync usually goes wrong)
- **Append-only history.** Every change is stored as a new row with a timestamp, never overwritten. Restore can use "now" or any earlier moment.
- **Mass-change guard.** If one poll would mark more than 25 items unwatched, or Kodi's library suddenly holds far fewer items (a wiped database looks exactly like that), muthur **stops following**. It keeps the last good state and shows a warning on the Dashboard until you confirm. A lost Kodi database therefore never wipes the backup.
- **Restore is never silent.** It shows a diff (n movies, m episodes, resume points) and needs a click. It only raises play counts and fills in missing resume points, unless you choose an exact restore.
- **Renames:** before a batch, muthur takes a fresh snapshot and refuses to start if Kodi can't be reached. After the batch, Kodi scans the changed folders and cleans the old paths. muthur then writes the status to the new paths, matched first by old → new path from its journal, then by ID. The batch is checked: every item that was watched before must be watched after.

**As built (0.6, 2026-10-25):**
- Polled every hour (and with *Back up now*) through JSON-RPC: `GetTVShows` for the show IDs, `GetEpisodes` and `GetMovies` for play count, last played and resume point. On the real library that's 5,338 items in about 4.5 s. The WebSocket notifications are not used yet; the hourly poll is the whole mechanism.
- Key: `ep:<id type>:<show id>:<season>:<episode>` or `movie:<id type>:<id>`, with TMDB, then IMDb, then TVDB as the ID used, and every ID Kodi knew stored next to it. A restore also matches on any shared ID, so a show Kodi later knows only by its TVDB ID still finds its history.
- Two files of the same episode or film are one item: the most-watched copy counts. Without this the copies flipped the stored state back and forth on every poll.
- Mass-change guard as designed: more than 25 items turning unwatched in one poll, or Kodi's library below 80 % of the last poll, pauses the backup with the reason on the Dashboard until the reader accepts Kodi's state.
- Restore is previewed (counts and titles), planned again when confirmed and refused if Kodi changed in between. It writes with `SetEpisodeDetails`/`SetMovieDetails` and only raises play counts or fills in missing resume points.
- Carrying status across muthur's own renames isn't needed yet: muthur only moves new downloads into the library. It comes with the library cleanup (phase 3), which renames existing files.

This needs Kodi's web server enabled (Settings → Services → Control) and the Shield on the network. Third-party services such as Trakt aren't needed for this. Trakt's free tier has been restricted since 2025 ([AlternativeTo](https://alternativeto.net/news/2025/2/trakt-tv-has-set-stricter-limits-for-free-users-and-raised-vip-subscription-prices-by-100-/)).

## 12. Existing library: dry run first

**Test plan:**

| Phase | What | Writes? |
|---|---|---|
| 0. Dry run, library | Run the identifier on every existing show and movie *as if it were a download*, and compare with the IDs already in their NFOs. Report: agreements, disagreements, held for review. Disagreements are either tool bugs or library mistakes. | No |
| 1. Leftover downloads | Finished downloads an earlier tool never imported. Small, real, and includes a show that's new to the library. | Yes, with undo |
| 2. New downloads | Normal use from here on. | Yes |
| 3. Library cleanup | Audit fixes in batches you approve: missing movies, misplaced content, duplicates, renames, NFO rewrite. Watched status carried over as in §11. | Yes, in batches |

Target before phase 3: ≥ 98 % agreement on the phase 0 sample, zero wrong *auto-accepts*. Anything uncertain may go to Review; nothing may be confidently wrong.

## 13. UI

A clickable mockup of all screens exists (private, because it shows real library data).

| Screen | Purpose |
|---|---|
| **Dashboard** | Counts (inbox, review, duplicates, health issues), last run, next score refresh, Kodi connection status. A **Process downloads** button. |
| **Inbox** | Everything in `complete/` with its status: ready, needs review, ignored (with reason), in progress. Preview of the planned target per item. |
| **Review** | One item at a time, keyboard-driven. Parsed info on the left, candidate cards (poster, year, plot, score breakdown) on the right. Pick one, search manually, or paste a TMDB/IMDb link. "Remember for this show" stores the alias. |
| **Library** | Poster grid or list of TV and Film. Filters (no NFO, no IMDb score, duplicates, no year). Detail panel: change the match, edit the title and other fields, see files and artwork, choose a different poster. |
| **Duplicates** | Side-by-side versions with quality details and the proposed winner. Confirm moves the loser to quarantine. |
| **Health** | The live audit: missing videos, orphan files, junk, broken names, folders without NFOs. Each issue has a one-click proposed fix. |
| **History** | Every run and item with what moved where. Undo per item or per run. |
| **Settings** | Paths, TMDB/fanart keys, title rule and language list, quality preferences, Kodi connection, schedule, dry-run switch. |

## 14. Security

- Deploy over SSH with a dedicated DSM admin user, key-only login (Docker on DSM needs root, so that user is powerful; SSH can be turned off after the build phase).
- The container itself runs **non-root** with access to `Iedereen` and its own config folder only.
- API keys live in `/config`, never in the image or the repo.
- The UI listens on the LAN only.

## 15. Milestones

1. **Parser + identifier CLI** run read-only against the library over SMB from the PC. Produces the phase 0 report. No container yet.
2. **Container skeleton** on Nostromo: FastAPI, SQLite, settings, Inbox (read-only), ID memory learned from the library, suspicious-file detection. Deploy steps in [DEPLOY.md](DEPLOY.md).
3. **Apply + journal/undo + NFO/artwork writer + Review** (done), then phase 1 on the leftover downloads (done: 23 items).
4. **IMDb scores + weekly refresh + Kodi JSON-RPC, including the watched-status backup (§11).** IMDb scores and the refresh: done (0.5). Watched-status backup with restore: done (0.6).
5. **Library, Duplicates, Health screens** and phase 3 cleanup with watched-status preservation.

## 16. Decisions on the former open questions (2026-10-24)

1. **Torrent client: Download Station.** "Finished" is read from the Download Station Web API (`SYNO.DownloadStation.Task`, `list` with status `finished`/`seeding`) as well as the 10-minute stability check. After a successful move, muthur removes the task through the same API, never before. A Sonarr user reported that removing Download Station tasks too early confused the importer ([Sonarr forum](https://forums.sonarr.tv/t/synology-download-station-not-completing-imports-solved/19865)). The exact `delete` parameters are checked against Synology's [Download Station Web API guide](https://cndl.synology.cn/download/Document/Software/DeveloperGuide/Package/DownloadStation/All/enu/Synology_Download_Station_Web_API.pdf) and tested on Nostromo. This needs a DSM account for muthur with Download Station rights only.
2. **Watched status must be kept.** See §11: Kodi is the master and muthur keeps a synced backup with restore. A cleanup batch stops if Kodi can't be reached or the restore can't be verified.
3. **No age ratings.** `mpaa` is not written.
4. **Actor photos: TMDB image links** in `<actor><thumb>`. Kodi downloads each once and caches it ([Kodi forum](https://forum.kodi.tv/showthread.php?tid=153424)). No `.actors` folders.
5. **No HDR.** The TV is SDR. HDR gets no bonus in the quality score, and an SDR copy is never beaten by an HDR copy just for being HDR.
