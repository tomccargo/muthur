# Installing muthur

muthur is one Docker container. It needs:

- **A machine that runs Docker Compose** and can reach your media folders: a Synology NAS with Container Manager (DSM 7.2 or later), or any Linux machine with Docker. Nothing in muthur is Synology-only except the optional Download Station clean-up.
- **One folder that holds the finished downloads, the TV library and the Film library** (for example a shared folder `media` with `downloads/complete`, `TV` and `Film` in it). One mount, so a move is an instant rename, never a copy.
- **Kodi** on any device (an NVIDIA Shield, a Fire TV, a LibreELEC box, a PC) that plays that library over the network.
- A free **TMDB "API Read Access Token"**: themoviedb.org → Settings → API.

The image is built by GitHub Actions and published as [`tomccargo/muthur`](https://hub.docker.com/r/tomccargo/muthur); nothing is built on the NAS.

## 1. A user for muthur

muthur runs as a user **without admin rights**, so even a bug in muthur can only touch what that user may touch. On a Synology: **Control Panel → User & Group → Create**, member of `users` only, with:

- **Read/Write** on the media shared folder and on the `docker` shared folder;
- every application denied (it never signs in).

You need its numbers (`PUID`, `PGID`). Over SSH: `id <user>` prints for example `uid=1032(media) gid=100(users)`, so `PUID=1032`, `PGID=100`.

## 2. The project folder

Make a folder for the project, for example `/volume1/docker/muthur`, with a `config` folder in it (File Station works). Put two files in it:

- `compose.yaml` from this repository;
- `.env`, a copy of [`.env.example`](../.env.example) with your values: `PUID`, `PGID`, `MEDIA_SHARE` (the folder from above), the folders inside it (`DOWNLOADS_DIR`, `TV_DIR`, `FILM_DIR`), `CONFIG_DIR` and `TZ`.

Docker Compose reads `.env` next to `compose.yaml` for the `${…}` values ([Docker docs](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)). If your Container Manager doesn't, write the values straight into `compose.yaml` instead.

Give muthur's user the config folder (over SSH): `sudo chown -R <user>:users /volume1/docker/muthur/config`.

## 3. Start it

- **Synology:** Container Manager → **Project** → **Create**: name `muthur`, path `/volume1/docker/muthur`, use the existing `compose.yaml`, then **Done**. Container Manager pulls the image and starts it.
- **Elsewhere:** `docker compose up -d` in the project folder.

On a Synology the project has a second container, **`muthur-relay`**. It removes a download's finished task from Download Station once muthur has filed it, tells the Inbox when Download Station has finished a download (no 10-minute wait), and lets you update muthur from Settings, all without a DSM password, so the DSM user that adds the downloads may keep two-step verification. It acts as the DSM user `PUID` belongs to; set `DS_USER` in `.env` when the tasks belong to another one. It runs as root with the host's process list and no network (ARCHITECTURE.md §14 says exactly what it may do). On any other machine, or if you don't want it, delete the `relay` service from `compose.yaml`. Settings then offer a DSM account (one without two-step verification) for the clean-up instead.

Open `http://<nas>:8580`. The first visit asks you to **choose a password**: do that right away, because until then anyone who opens the page can choose it. Then, in **Settings**: the TMDB token (unless it's in `.env`), the Kodi address, and whether to start in **dry run** (plans only, changes nothing).

**Short addresses (Synology, optional).** `http://<nas>/kodi` and `http://<nas>/player` open the player and `http://<nas>/muthur` the dashboard, so nobody has to remember the port. They are redirects in DSM's own web server, next to its `/download` alias; muthur stays on 8580. Over SSH, as root: copy `scripts/nas/short-paths.conf` and `install-short-paths.sh` to `/volume1/docker/muthur/nas/` and run the script. DSM gives no promise to keep a file it didn't write through an update, so add a **Task Scheduler → Create → Triggered Task → User-defined script**, user root, event **Boot-up**, running that script: it puts the addresses back when they are missing and does nothing otherwise.

## 4. Kodi

In Kodi, **Settings → Services → Control**:

- **Allow remote control via HTTP** on, with a username and password: muthur asks Kodi to scan and to re-read the NFOs it changed.
- **Allow remote control from applications on other systems** on: Kodi then tells muthur when something was watched (port 9090, settable in muthur).

Add the TV and Film folders as **video sources** (over SMB or NFS), with **Local information only** as the information provider: muthur writes the NFOs and artwork, so Kodi never has to scrape. muthur finds each source by its folder's name, so the folder names on the NAS and in Kodi must be the same (`TV` and `TV`, `Series` and `Series`).

**Waking an Android TV box (optional).** On an NVIDIA Shield or another Android TV device, muthur can wake the box and start Kodi when you start something that needs it. Turn on **Developer options → Network debugging** on the box, then in muthur's Settings read the box's apps, choose Kodi, and accept muthur on the TV once.

## 5. Updating

The project uses `tomccargo/muthur:latest` unless `.env` sets `MUTHUR_VERSION`.

**Update only while muthur is idle.** An update restarts the container; a job running then is cut off. muthur picks
up a cut-off rename's Kodi step after the restart, but nothing else of that job. Check first: `"busy": false` from
```bash
docker exec muthur python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8580/api/health')))"
```

- **Synology, from muthur's Settings (0.57):** with `muthur-relay` running, **Settings → muthur → Update muthur** pulls the image, waits until muthur is idle, and has Container Manager rebuild the project; the page reloads with the new version. `MUTHUR_UPDATES=off` in `.env` removes the button. The first time, after adding the relay, update once in one of the ways below.
- **Synology, from the NAS's own screens:** Container Manager → **Image**: `tomccargo/muthur` shows *Update available*; update it, then recreate the container (Project → muthur → stop and start, or Container → muthur → Action → Reset). This is how community guides describe it ([drfrankenstein](https://drfrankenstein.co.uk/updating-containers-in-the-synology-docker-package/comment-page-1)); Container Manager may take a day to notice a new image.
- **Synology, over SSH (as root):** pull the image and let Container Manager rebuild the project with [`scripts/nas-update-project.py`](../scripts/nas-update-project.py), which finds the project by its name:
  ```bash
  docker pull tomccargo/muthur:latest && python3 /volume1/docker/muthur/nas-update-project.py /volume1/docker/muthur/compose.yaml
  ```
- **Elsewhere:** `docker compose pull && docker compose up -d`.

The running version: `docker exec muthur python -c "import muthur; print(muthur.__version__)"`.

## 6. Forgotten password

Run `muthur password` inside the container: Container Manager → Container → muthur → **Open Terminal** (the image has `sh`, not `bash`), or over SSH `sudo docker exec -it muthur muthur password`. Every browser then signs in with the new one.

muthur keeps only a one-way (scrypt) hash of the password, so a forgotten one can't be read back, only replaced.

**No login at all:** set `MUTHUR_AUTH=0` in `.env` and recreate the container (§5). The login page goes away and anyone who can reach the address can use every button, so do this only on a network you alone use. The stored password stays in the database; remove the line (or set `1`) to bring the login back. `/api/owned` keeps needing its own key either way.

## 7. Another app that reads what you own (optional)

`GET /api/owned` lists every show and film on disk by its TMDB and IMDb ID, with the episodes of each season, for another app on the LAN that hides what you already have (such as lambert):

```json
{"tv": [{"tmdb": 1399, "imdb": "tt0944947", "seasons": {"1": [1, 2, 3]}}], "film": [{"tmdb": 603, "imdb": "tt0133093"}]}
```

It is **off** until `.env` sets `MUTHUR_OWNED_KEY`, a key of its own (not the UI password) that only reads this list. Make one with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, put it in `.env`, and recreate the container (§5). The other app sends it as `Authorization: Bearer <key>`; a missing or wrong key gets 401, and without a key set the address answers 404. The list comes from the last library index (the Library page's, or the daily check's), so it costs no disk scan. Removing the key from `.env` turns it off again.

## 8. Guardrails

`docker stats muthur --no-stream` shows the memory in use: well under the 256 MB limit (`MEMORY_LIMIT` in `.env`), about 70 MB idle. If DSM warns that the kernel doesn't support swap limits, that's expected; the memory limit still applies.
