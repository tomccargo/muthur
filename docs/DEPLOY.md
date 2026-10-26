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

Open `http://<nas>:8580`. The first visit asks you to **choose a password**: do that right away, because until then anyone who opens the page can choose it. Then, in **Settings**: the TMDB token (unless it's in `.env`), the Kodi address, and whether to start in **dry run** (plans only, changes nothing).

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

- **Synology, from the NAS's own screens:** Container Manager → **Image**: `tomccargo/muthur` shows *Update available*; update it, then recreate the container (Project → muthur → stop and start, or Container → muthur → Action → Reset). This is how community guides describe it ([drfrankenstein](https://drfrankenstein.co.uk/updating-containers-in-the-synology-docker-package/comment-page-1)); Container Manager may take a day to notice a new image.
- **Synology, over SSH (as root):** pull the image and let Container Manager rebuild the project with [`scripts/nas-update-project.py`](../scripts/nas-update-project.py), which finds the project by its name:
  ```bash
  docker pull tomccargo/muthur:latest && python3 /volume1/docker/muthur/nas-update-project.py /volume1/docker/muthur/compose.yaml
  ```
- **Elsewhere:** `docker compose pull && docker compose up -d`.

The running version: `docker exec muthur python -c "import muthur; print(muthur.__version__)"`.

## 6. Forgotten password

Run `muthur password` inside the container: Container Manager → Container → muthur → **Open Terminal** (the image has `sh`, not `bash`), or over SSH `sudo docker exec -it muthur muthur password`. Every browser then signs in with the new one.

## 7. Guardrails

`docker stats muthur --no-stream` shows the memory in use: well under the 256 MB limit (`MEMORY_LIMIT` in `.env`), about 70 MB idle. If DSM warns that the kernel doesn't support swap limits, that's expected; the memory limit still applies.
