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

- The container runs as a dedicated user without admin rights (PUID/PGID) with read/write on the media folder only.
- The web UI is on the LAN only (for example `http://nostromo:8580`) and asks for a password (§14).
- `quarantine` lives at `/data/_muthur-quarantine` (`QUARANTINE_DIR`).
- **Where settings live (0.21).** The install's settings are in `.env` next to `compose.yaml` (see `.env.example`): user, the media folder and the folders inside it, the config folder, port, time zone, image version. A missing required one stops `docker compose` with a message instead of guessing. Everything changed while using muthur is in Settings, stored in its database: Kodi (HTTP and notification ports), the box to wake, the TMDB token and the language of plots and episode titles, Download Station, the title rule, dry run. A TMDB token saved in Settings wins over the one in `.env`; removing it brings that one back. Saved secrets can be removed.
- **One job at a time, the rest wait (0.24).** A job started while another runs waits in a queue and starts by itself (the same job is never queued twice); the job bar says what comes next. Edits made right on a page still wait for nothing: while a job runs or waits, they say so.
- **Told on the TV (0.24).** When Kodi is on, a short Kodi notification (`GUI.ShowNotification`) says what a job you started did, if it took more than half a minute ("4,534 fix(es) done."), anything that needs you (a run that couldn't put everything back), a job that stopped with a problem, and a watched backup that paused (told once). The schedule's own jobs stay quiet. muthur never wakes the box for a notification.
- **Questions can be left as is (0.24).** A Health question (or every question of a show) can be left as is; muthur remembers it by its place and wording, so it comes back when the situation changes. "Show the N left as is" lists them with "Ask again".
- **Suspicious and packed downloads can go to quarantine (0.24)** from the Inbox, as a journalled run, instead of "delete it yourself".
- **Getting started (0.24).** Until the TMDB token, the Kodi connection and a first check of the downloads are done (and Kodi has a video source for each library folder, when it answers), the Dashboard shows a checklist that ticks itself.
- **Names (0.22).** The pages call the NAS and the box Kodi runs on by the names in Settings ("Kodi on the Shield", the Dashboard's small title); a new install says "Kodi device" and "NAS".
- **Kodi's sources are found by folder name (0.21).** muthur matches each library folder to the Kodi video source ending in the same folder name, so `Series` and `Movies` work as well as `TV` and `Film`.

## 4. Data sources

| Source | Used for | Cost / terms |
|---|---|---|
| **TMDB API** | Identification, titles, plots, cast, artwork, TMDB scores, season/episode structure, specials, anime episode groups | Free for non-commercial use with attribution ([TMDB FAQ](https://developer.themoviedb.org/docs/faq)). Needs your own API key. The UI shows "Data from TMDB". |
| **IMDb datasets** | IMDb scores for movies, shows **and episodes** | Free daily files for personal, non-commercial use ([IMDb](https://developer.imdb.com/non-commercial-datasets/)). Uses `title.episode` and `title.ratings`. |
| Existing NFOs | ID memory: 179 shows already have TVDB/TMDB/IMDb IDs | Read once at import |
| fanart.tv (optional, not built) | `clearlogo.png`, `landscape.jpg`, `banner.jpg` | Free personal API key. TMDB's logos cover `clearlogo.png`; nothing reads fanart.tv yet. |
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
- **Subtitles** follow their video: `.en.srt`, `.nl.srt`, `.en.forced.srt`. Only language or subtitle tags may follow the video's name, so `Dune.Part.Two.2024.en.srt` never goes with `Dune.mkv` (0.20). A `Subs` folder in the download is read too: `Subs/<video name>/2_English.srt` in a season pack, `Subs/2_English.srt` when the download holds one video; they become `<new name>.English.srt`.
- **Junk** (tracker `.txt`, `.exe`, samples, `.part`, `Screens/`) is not copied. When a torrent folder holds only junk after the move, the folder goes to quarantine.

### 5.5 Apply
- Every operation is written to a **journal** first (from, to, hash of the first and last 1 MB, timestamp), then executed.
- **Undo** replays the journal in reverse, per item or per run.
- Never overwrite, never delete: anything that would be lost goes to quarantine.
- **Dry run** is a global switch. Everything up to Apply runs and the plan is shown, but nothing is written. *Built (0.15):* Settings → Changes to the library. While it is on, Apply, Duplicates, Health fixes, emptying the quarantine and the score refresh refuse with a sentence saying so; checks and Review choices still work.

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
3. HDR: no bonus (the TV is SDR); *since 0.15 a setting, measured from the colour transfer (PQ, HLG) or read from the name*
4. Video codec: AV1 ≈ HEVC > H.264 > older
5. Audio: lossless/Atmos > 5.1 > stereo
6. Bitrate per minute (a tiebreaker against over-compressed encodes)
7. Subtitles present (en/nl)

The tool proposes a winner and you confirm.

**As built (0.8, 2026-10-25):** groups are episode numbers held by more than one video in a show (joined through double episodes; damaged numbers left out) and films sharing an IMDb or TMDB ID. Each copy is measured with ffprobe (cached by size and modification time; about 0.3 s a file) and its source read from the name; the rank is source, resolution, codec, audio, bitrate, subtitles, and a copy ffprobe can't read is never kept. Between equals, the copy with an NFO in a proper season or show folder wins. The kept video takes the name of the best-named copy with an NFO (muthur's, else one named after the show), with the resolution in the name corrected; that copy's NFO, thumbnail and subtitles keep matching, and a subtitle the kept copy lacks comes from another copy. Films in folders end up in the curated `Title (Year)` folder as `Title (Year).ext`; other folders go to quarantine whole. Applying needs Kodi: muthur takes a fresh watched backup, re-checks every copy's size, journals each move, then has Kodi scan the folder, gives the kept item the highest play count (or resume point) of all copies and removes the old entries. On the real library: 97 groups (86 episodes, 11 films). Losers go to `_muthur-quarantine/<date>/` under their library path; the journal (History) says why. Not built yet: a JSON note next to each quarantined file, and emptying the quarantine from the UI.

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
- Polled every hour (and with *Back up now*) through JSON-RPC: `GetTVShows` for the show IDs, `GetEpisodes` and `GetMovies` for play count, last played and resume point. On the real library that's 5,338 items in about 4.5 s. Since 0.13 muthur also listens to Kodi's notifications on its TCP JSON-RPC port 9090 ("Allow remote control from applications on other systems", on at the Shield): after `VideoLibrary.OnUpdate`, `Player.OnStop`, `OnRemove` or `OnScanFinished`, a backup runs once Kodi has been quiet for 30 s, with the same mass-change guard. The hourly poll stays as the safety net, and the Dashboard says whether the live connection is up. Since 0.16, when the Shield sleeps (Kodi then answers on neither port), the scan after an Apply waits: as soon as Kodi answers on 9090 again, muthur asks it to scan and takes a backup. Since 0.17 muthur can also wake the Shield and start the media app over ADB (network debugging), but only for something the reader starts (Apply, undo, Duplicates, Restore, Back up now, Wake now), never from a schedule; the app and its launch activity are read from the Shield and chosen in Settings, the port is a setting. Tested 2026-10-25: ADB woke the Shield from sleep and started Kodi every time; the Android TV Remote protocol (paired) neither woke it nor started Kodi (the launch link `market://launch?id=` was refused). HDMI-CEC is left on, so waking may switch the TV's input.
- Key: `ep:<id type>:<show id>:<season>:<episode>` or `movie:<id type>:<id>`, with TMDB, then IMDb, then TVDB as the ID used, and every ID Kodi knew stored next to it. A restore also matches on any shared ID, so a show Kodi later knows only by its TVDB ID still finds its history.
- Two files of the same episode or film are one item: the most-watched copy counts. Without this the copies flipped the stored state back and forth on every poll.
- Mass-change guard as designed: more than 25 items turning unwatched in one poll, or Kodi's library below 80 % of the last poll, pauses the backup with the reason on the Dashboard until the reader accepts Kodi's state.
- Restore is previewed (counts and titles), planned again when confirmed and refused if Kodi changed in between: the preview carries a fingerprint of the exact changes, not only their number (0.20). It writes with `SetEpisodeDetails`/`SetMovieDetails` and only raises play counts or fills in missing resume points.
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

**Phase 3 as built (0.9, 2026-10-25): the Health page.** A check reads the library index and sorts every problem into a fix muthur can make without a guess, or a question for the reader. Fixes are chosen per kind and applied as one journalled run that History can put back:
- *Add IMDb scores to NFOs* that have none (also NFOs from other tools): only the IMDb entry is added and made the default; other ratings stay; a copy of each old NFO is kept; Kodi re-reads each item.
- *Write NFOs for episodes that have none*, and *tvshow.nfo* for show folders muthur can place on TMDB (through the NFO, its show memory, or the TVDB ID).
- *Move leftover files* (tracker notes, `Thumbs.db`, NFOs and thumbnails of videos that are gone) and *film folders without a video* to quarantine.

Episodes are only written or scored when they are single episodes and the title in the file name doesn't belong to another TMDB episode. In a season the library numbers beyond TMDB's count, an episode is only fixed when the title in its name confirms TMDB's title at its number (nearly equal, or one contains the other); the rest of that season is listed. Since 0.11 the season's own episode list is used for the count, because TMDB's per-show counts are cached longer. Everything else is listed under *Needs you*: shows muthur can't place, seasons numbered differently, damaged numbers, films without an NFO.

On the real library (2026-10-25): 4,462 IMDb scores, 82 episode NFOs, 158 leftovers and 11 empty film folders can be fixed; 30 seasons, 134 episode numbers, 137 films and 19 shows need the reader. Since 0.10, shows and films without IDs are looked up on TMDB like downloads (name, year, episodes or length) and fixed only on a certain match; the weekly score refresh also updates the IMDb scores Health added to other tools' NFOs, and never removes one there. Since 0.12, a show or film muthur can't place gets *Which is it?* in the list: a TMDB search whose answer counts as certain (a show is remembered for its folder, a film's choice for its file), and that item is checked again on the spot. The quarantine is listed per day under Health; emptying a day deletes it for good and only happens on the reader's confirmation.

## 13. UI

A clickable mockup of all screens exists (private, because it shows real library data). The table says what each screen does as built (0.22); the look and rules are in [DESIGN.md](../DESIGN.md).

| Screen | Purpose |
|---|---|
| **Dashboard** | Counts (ready, needs you, still downloading, ignored), Kodi's connection with a wake button, the watched-status backup, IMDb scores and their next refresh, the library's duplicates and fixes. One button: **Check downloads**. |
| **Inbox** | Everything in `complete/` with its status: ready, needs review, ignored (with reason), in progress. Preview of the planned target per item. |
| **Review** | One item at a time, with keyboard shortcuts. What the name says, and candidate cards (poster, year, plot, why it matched). Pick one, search TMDB, or paste a TMDB/IMDb link; per episode, choose the TMDB episode and which number the file keeps. "Remember for this show" stores the alias. |
| **Library** | TV and Film with posters, scores and watched status, searchable. Filters: missing NFO, no IMDb score, duplicates, damaged names. A show's page lists its episodes and loose files. Change a show's or film's match, its title, or its poster; each change can be put back from History. |
| **Duplicates** | Each group's copies with measured quality and the proposed copy to keep (changeable). Confirming moves the others to quarantine and carries the watched status over; the Quarantine panel shows why each item is there and can empty days for good. |
| **Health** | Checked daily and on demand. Fixes muthur can make without guessing (leftovers, empty film folders, missing NFOs, IMDb scores, subtitles Kodi can't find: English beside the video under its name, Dutch only when there is no English, other languages to quarantine; missing or poor posters; episodes and films renamed to the library's naming while Kodi is on, keeping their watched status; release notes named like an NFO but for capitals; old Kodi entries for a video that moved or is listed twice, removed after their watched status went to the entry that stays), applied in batches you choose; questions it can't answer alone (which show or film a folder is, numbering that differs from TMDB). Every check also looks for duplicates again (0.40): an NFO written since can make two copies the same film. |
| **History** | Every run and item with what moved where. Undo per item or per run. |
| **Settings** | Dry run and the HDR preference; the TMDB token (where it comes from, removing a saved one) and the language of plots and episode titles; Kodi (address, ports, login) and waking the Kodi box; Download Station; names; the password; which languages keep their original film title; the folders, read-only (they come from `.env`). No schedule setting: the schedule is fixed (§8, §11, §12). |

## 14. Security

- Deploy over SSH with a dedicated DSM admin user, key-only login (Docker on DSM needs root, so that user is powerful; SSH can be turned off after the build phase).
- The container itself runs **non-root** with access to `Iedereen` and its own config folder only.
- API keys live in `/config`, never in the image or the repo.
- The UI listens on the LAN only.
- **The journal comes first (0.20).** Every folder, move, new file and rewrite goes through one set of journal functions: the change is recorded as failed, made, then marked done with its fingerprint. A crash halfway leaves a record, never an unknown file.
- **Signing in (0.19).** The first visit chooses a password (at least 8 characters), stored as an scrypt hash. A browser that signs in gets a random session cookie (HttpOnly, SameSite=Strict, 30 days of use; stored hashed). Every API call except the container's health check needs it. Five wrong passwords from one address mean a five-minute pause. A new password signs every other browser out. Forgotten: `muthur password` in the container's terminal sets a new one. `MUTHUR_AUTH=0` switches the password off, only for tests or behind a proxy with its own login.
- **Other websites can't press muthur's buttons (0.19).** A request that changes something is refused when the browser says it comes from another site (`Sec-Fetch-Site`, else `Origin`), following [OWASP's CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html). FastAPI already refuses JSON bodies sent as plain text ([CVE-2021-32677](https://nvd.nist.gov/vuln/detail/cve-2021-32677)), but requests without a body weren't covered. The SameSite cookie also stops a DNS-rebinding page, which would have to call muthur under its own name and so never has the cookie ([NCC Group](https://github.com/nccgroup/singularity/wiki/Preventing-DNS-Rebinding-Attacks)).
- **What the API accepts (0.19).** Apply only takes downloads that are in the inbox, never a path. The Shield's app must look like an Android component (`package/activity`) and is quoted before it reaches `adb shell`, which runs its arguments through the box's shell. A new Kodi or Download Station address forgets the stored password, so it never goes to another machine. Download Station's certificate is checked. Undo is refused in a dry run, like every other change. Edits made from a page (Library, Review, Health questions, emptying the quarantine) take the same one-at-a-time slot as the jobs, so a scheduled job can't write the same file at the same moment.

## 15. Milestones

1. **Parser + identifier CLI** run read-only against the library over SMB from the PC. Produces the phase 0 report. No container yet.
2. **Container skeleton** on Nostromo: FastAPI, SQLite, settings, Inbox (read-only), ID memory learned from the library, suspicious-file detection. Deploy steps in [DEPLOY.md](DEPLOY.md).
3. **Apply + journal/undo + NFO/artwork writer + Review** (done), then phase 1 on the leftover downloads (done: 23 items).
4. **IMDb scores + weekly refresh + Kodi JSON-RPC, including the watched-status backup (§11).** IMDb scores and the refresh: done (0.5). Watched-status backup with restore: done (0.6).
5. **Library, Duplicates, Health screens** and phase 3 cleanup with watched-status preservation. Library: done (0.7); changing a show's or film's match, its title and its poster from the Library: done (0.18), each edit a run History can put back. Duplicates: done (0.8). Health: done (0.9), described in §12 below. An index of every show, episode and film (NFO facts, the score Kodi shows, watched status from the backup, problems) is built daily and on demand; NFOs are cached by modification time, so a re-index of the real library takes about 30 s. Library images are served only from the TV and Film folders, and only as images.

## 16. Decisions on the former open questions (2026-10-24)

1. **Torrent client: Download Station.** "Finished" is read from the Download Station Web API (`SYNO.DownloadStation.Task`, `list` with status `finished`/`seeding`) as well as the 10-minute stability check. After a successful move, muthur removes the task through the same API, never before. A Sonarr user reported that removing Download Station tasks too early confused the importer ([Sonarr forum](https://forums.sonarr.tv/t/synology-download-station-not-completing-imports-solved/19865)). The exact `delete` parameters are checked against Synology's [Download Station Web API guide](https://cndl.synology.cn/download/Document/Software/DeveloperGuide/Package/DownloadStation/All/enu/Synology_Download_Station_Web_API.pdf) and tested on Nostromo. This needs the DSM account that owns the tasks: Download Station shows an account only its own tasks. On Nostromo all tasks belong to `torrent` (checked 2026-10-25), the user muthur's container already runs as. **As built (0.11):** Settings take the NAS address, that account and its password; after an Apply, muthur logs in with `SYNO.API.Auth` v7 (`entry.cgi`; since 0.23 as a form POST, so the password never sits in a URL or DSM's logs: Synology's guide shows GET, but DSM 7.3's `entry.cgi` takes the same fields as POST), lists tasks with `SYNO.DownloadStation.Task` v1 (`DownloadStation/task.cgi`, which DSM 7.3 on Nostromo offers next to the newer `SYNO.DownloadStation2.Task`) and deletes, with `force_complete=false`, only the tasks that are finished or seeding and whose title is the name of a download it just moved. A task still downloading is left alone and reported.
2. **Watched status must be kept.** See §11: Kodi is the master and muthur keeps a synced backup with restore. A cleanup batch stops if Kodi can't be reached or the restore can't be verified.
3. **No age ratings.** `mpaa` is not written.
4. **Actor photos: TMDB image links** in `<actor><thumb>`. Kodi downloads each once and caches it ([Kodi forum](https://forum.kodi.tv/showthread.php?tid=153424)). No `.actors` folders.
5. **No HDR.** The TV is SDR. HDR gets no bonus in the quality score, and an SDR copy is never beaten by an HDR copy just for being HDR.
