"""Kodi JSON-RPC over HTTP: is Kodi there, scan for new files, re-read an item's NFO."""
from __future__ import annotations

import os

import requests


def folder_name(root: str) -> str:
    """The last folder of a library root: '/data/Series' -> 'Series'. Kodi's source for it ends in that name."""
    return os.path.basename(os.path.normpath(root))


class Kodi:
    def __init__(self, host: str, port: int = 8080, user: str | None = None, password: str | None = None, timeout: float = 4,
                 device: str = "Kodi device"):
        """device: what the reader calls the box Kodi runs on (Settings, Names), for the sentences below."""
        self.device = device
        self.session = requests.Session()  # one connection for a batch of calls, not one per call
        self.url = f"http://{host}:{port}/jsonrpc"
        self.auth = (user, password or "") if user else None
        self.timeout = timeout

    def call(self, method: str, params: dict | None = None):
        r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                              auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "Kodi returned an error"))
        return body.get("result")

    def source_prefix(self, name: str) -> str | None:
        """Kodi's path of the video source whose folder has this name: 'Series' -> 'smb://nas/media/Series/'."""
        for s in (self.call("Files.GetSources", {"media": "video"}) or {}).get("sources", []):
            path = s.get("file", "")
            if path.rstrip("/").rsplit("/", 1)[-1].lower() == name.lower():
                return path if path.endswith("/") else path + "/"
        return None

    def scan_and_wait(self, directory: str | None = None, limit: float = 300) -> bool:
        """Scan (one folder, or everything) and wait until Kodi is done. False when it took too long."""
        import time

        self.call("VideoLibrary.Scan", {"directory": directory} if directory else {})
        time.sleep(2)
        end = time.time() + limit
        while time.time() < end:
            state = self.call("XBMC.GetInfoBooleans", {"booleans": ["Library.IsScanningVideo"]}) or {}
            if not state.get("Library.IsScanningVideo"):
                return True
            time.sleep(2)
        return False

    def refresh_files(self, paths: list[str], roots: dict[str, str], progress=None) -> dict:
        """Ask Kodi to re-read the NFOs at these paths. roots maps each library ('TV', 'Film') to muthur's
        folder for it ('/data/Series'); Kodi's path is matched by that folder's name ('smb://nas/media/Series/…'),
        whatever the folders are called. Returns counts; an item Kodi doesn't have is skipped.
        progress(done, total) after each path: a library-wide batch is thousands of calls."""
        done = missing = 0
        shows: list | None = None  # Kodi's show list, read once for the whole batch
        for n, path in enumerate(paths, 1):
            try:
                if shows is None and path.endswith("tvshow.nfo"):
                    shows = self.call("VideoLibrary.GetTVShows", {"properties": ["file"]}).get("tvshows", [])
                done += self._refresh_one(path, roots, shows or [])
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                # Kodi went away (the box slept): the rest can't be told either, and they aren't 'not in Kodi'.
                return {"refreshed": done, "notInKodi": missing, "kodiAway": len(paths) - n + 1}
            except LookupError:
                missing += 1
            except (requests.exceptions.RequestException, RuntimeError):
                missing += 1
            if progress:
                progress(n, len(paths))
        return {"refreshed": done, "notInKodi": missing}

    def _refresh_one(self, path: str, roots: dict[str, str], shows: list) -> int:
        lib = next((k for k, r in roots.items() if path.startswith(r.rstrip("/\\") + os.sep) or path.startswith(r.rstrip("/") + "/")), None)
        if lib is None:
            raise LookupError(path)
        root = roots[lib]
        rel = folder_name(root) + "/" + os.path.relpath(path, root).replace(os.sep, "/")
        folder, name = rel.rsplit("/", 1)

        def ends(kodi_path: str, suffix: str) -> bool:
            return kodi_path.replace("\\", "/").rstrip("/").lower().endswith("/" + suffix.lower())

        if name == "tvshow.nfo":
            for s in shows:
                if ends(s["file"], folder):
                    self.call("VideoLibrary.RefreshTVShow", {"tvshowid": s["tvshowid"], "refreshepisodes": False})
                    return 1
            raise LookupError(path)
        # Any other NFO sits next to its video, under the same name: an episode in TV, a film elsewhere.
        stem = name[:-4]
        method, key, refresh, id_key = (("VideoLibrary.GetEpisodes", "episodes", "VideoLibrary.RefreshEpisode", "episodeid")
                                        if lib == "TV" else
                                        ("VideoLibrary.GetMovies", "movies", "VideoLibrary.RefreshMovie", "movieid"))
        found = self.call(method, {"properties": ["file"], "filter": {"field": "filename", "operator": "startswith", "value": stem}})
        for x in (found or {}).get(key, []):
            if ends(x["file"].rsplit(".", 1)[0], f"{folder}/{stem}"):
                self.call(refresh, {id_key: x[id_key]})
                return 1
        raise LookupError(path)

    def notify(self, title: str, message: str, ms: int = 8000) -> bool:
        """A short message on the TV (GUI.ShowNotification, displaytime in ms). False when Kodi doesn't answer:
        never retried, and nothing is woken for it."""
        try:
            self.call("GUI.ShowNotification", {"title": title, "message": message, "displaytime": ms})
            return True
        except (requests.exceptions.RequestException, RuntimeError, ValueError):
            return False

    def check(self) -> dict:
        """{'connected': True, 'version': '21.3'} or {'connected': False, 'problem': '…'}: a sentence a reader can act on."""
        try:
            if self.call("JSONRPC.Ping") != "pong":
                return {"connected": False, "problem": "Kodi answered, but not as expected."}
            v = self.call("Application.GetProperties", {"properties": ["version"]})["version"]
            return {"connected": True, "version": f"{v['major']}.{v['minor']}"}
        except requests.exceptions.ConnectTimeout:
            return {"connected": False, "problem": f"Kodi didn't answer. Is the {self.device} on?"}
        except requests.exceptions.ConnectionError:
            return {"connected": False, "problem": f"Kodi isn't running on the {self.device} (asleep, or Kodi is closed). "
                                                  "If it is on, check “Allow remote control via HTTP” and the port."}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return {"connected": False, "problem": "Kodi refused the username or password."}
            return {"connected": False, "problem": f"Kodi answered with an error ({e.response.status_code if e.response is not None else '?'})."}
        except (requests.exceptions.RequestException, RuntimeError, KeyError, ValueError) as e:
            return {"connected": False, "problem": f"Couldn't talk to Kodi: {e}"}
