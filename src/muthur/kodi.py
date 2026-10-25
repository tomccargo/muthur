"""Kodi JSON-RPC over HTTP: is Kodi there, scan for new files, re-read an item's NFO."""
from __future__ import annotations

import os

import requests


class Kodi:
    def __init__(self, host: str, port: int = 8080, user: str | None = None, password: str | None = None, timeout: float = 4):
        self.url = f"http://{host}:{port}/jsonrpc"
        self.auth = (user, password or "") if user else None
        self.timeout = timeout

    def call(self, method: str, params: dict | None = None):
        r = requests.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                          auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "Kodi returned an error"))
        return body.get("result")

    def refresh_files(self, paths: list[str], shares: dict[str, str]) -> dict:
        """Ask Kodi to re-read the NFOs at these paths. shares maps muthur's library roots to the
        name of the same folder on the share ('/data/TV' -> 'TV'), so 'smb://nostromo/iedereen/TV/…'
        matches. Returns counts; an item Kodi doesn't have is skipped."""
        done = missing = 0
        for path in paths:
            try:
                done += self._refresh_one(path, shares)
            except LookupError:
                missing += 1
            except (requests.exceptions.RequestException, RuntimeError):
                missing += 1
        return {"refreshed": done, "notInKodi": missing}

    def _refresh_one(self, path: str, shares: dict[str, str]) -> int:
        root = next((r for r in shares if path.startswith(r.rstrip("/") + "/")), None)
        if root is None:
            raise LookupError(path)
        rel = shares[root] + "/" + os.path.relpath(path, root).replace(os.sep, "/")
        folder, name = rel.rsplit("/", 1)

        def ends(kodi_path: str, suffix: str) -> bool:
            return kodi_path.replace("\\", "/").rstrip("/").lower().endswith("/" + suffix.lower())

        if name == "tvshow.nfo":
            for s in self.call("VideoLibrary.GetTVShows", {"properties": ["file"]}).get("tvshows", []):
                if ends(s["file"], folder):
                    self.call("VideoLibrary.RefreshTVShow", {"tvshowid": s["tvshowid"], "refreshepisodes": False})
                    return 1
            raise LookupError(path)
        # Any other NFO sits next to its video, under the same name: an episode in TV, a film elsewhere.
        stem = name[:-4]
        method, key, refresh, id_key = (("VideoLibrary.GetEpisodes", "episodes", "VideoLibrary.RefreshEpisode", "episodeid")
                                        if shares[root] == "TV" else
                                        ("VideoLibrary.GetMovies", "movies", "VideoLibrary.RefreshMovie", "movieid"))
        found = self.call(method, {"properties": ["file"], "filter": {"field": "filename", "operator": "startswith", "value": stem}})
        for x in (found or {}).get(key, []):
            if ends(x["file"].rsplit(".", 1)[0], f"{folder}/{stem}"):
                self.call(refresh, {id_key: x[id_key]})
                return 1
        raise LookupError(path)

    def check(self) -> dict:
        """{'connected': True, 'version': '21.3'} or {'connected': False, 'problem': '…'}: a sentence a reader can act on."""
        try:
            if self.call("JSONRPC.Ping") != "pong":
                return {"connected": False, "problem": "Kodi answered, but not as expected."}
            v = self.call("Application.GetProperties", {"properties": ["version"]})["version"]
            return {"connected": True, "version": f"{v['major']}.{v['minor']}"}
        except requests.exceptions.ConnectTimeout:
            return {"connected": False, "problem": "Kodi didn't answer. Is the Shield on?"}
        except requests.exceptions.ConnectionError:
            return {"connected": False, "problem": "Nothing is listening there. Is “Allow remote control via HTTP” on in Kodi, and is the port right?"}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return {"connected": False, "problem": "Kodi refused the username or password."}
            return {"connected": False, "problem": f"Kodi answered with an error ({e.response.status_code if e.response is not None else '?'})."}
        except (requests.exceptions.RequestException, RuntimeError, KeyError, ValueError) as e:
            return {"connected": False, "problem": f"Couldn't talk to Kodi: {e}"}
