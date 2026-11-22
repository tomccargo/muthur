"""Synology Download Station: which downloads are finished, and removing a finished task once muthur has moved its files
(ARCHITECTURE.md §16).

Two ways in, with the same methods (tasks, remove_finished, check):

- Relay: muthur's relay container (relay.py) runs DSM's own synowebapi as the DSM user that owns the tasks, so no password
  is stored and that user may keep two-step verification. muthur talks to it through files in config/relay.
- DownloadStation: the Web API in Synology's Download Station developer guide, logging in with a DSM account (one without
  two-step verification): SYNO.API.Auth (entry.cgi), SYNO.DownloadStation.Task (task.cgi). For a NAS without the relay.

A task is only removed after its download was moved successfully, never before, and only when it is finished or seeding.
"""
from __future__ import annotations

import json
import os
import time
import uuid

import requests

DONE = {"finished", "seeding"}
ALIVE = 60  # the relay writes relay.alive every 15 s; older than this, it isn't running


class DownloadStationError(Exception):
    """A sentence for the reader."""


AUTH_ERRORS = {400: "The account or password is wrong.", 401: "That account is disabled.", 402: "That account may not use Download Station.",
               403: "That account uses two-step verification; give muthur an account without it.", 407: "The NAS blocked this address after failed logins."}


class _Tasks:
    """What both ways share: the clean-up after a move."""

    def tasks(self) -> list[dict]:
        raise NotImplementedError

    def _delete(self, ids: list[str]) -> None:
        raise NotImplementedError

    def remove_finished(self, titles: set[str]) -> dict:
        """Delete the finished or seeding tasks with these titles (the names of downloads muthur moved)."""
        matches = [t for t in self.tasks() if t["title"] in titles]
        done = [t for t in matches if t["status"] in DONE]
        if done:
            self._delete([t["id"] for t in done])
        return {"removed": [t["title"] for t in done], "notFinished": [t["title"] for t in matches if t["status"] not in DONE]}

    def by_title(self) -> dict[str, dict]:
        """The tasks by title (a download's top-level name), for the Inbox."""
        return {t["title"]: t for t in self.tasks() if t.get("title")}

    def check(self) -> dict:
        try:
            return {"connected": True, "tasks": len(self.tasks())}
        except DownloadStationError as e:
            return {"connected": False, "problem": str(e)}


class Relay(_Tasks):
    """muthur's relay container, through request and answer files in its spool folder."""

    def __init__(self, spool: str, timeout: float = 45):
        self.spool, self.timeout = spool, timeout

    def state(self) -> dict | None:
        """What the relay last said about itself ({at, user, updates}), or None when it isn't running."""
        try:
            with open(os.path.join(self.spool, "relay.alive"), encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            return None
        return state if isinstance(state, dict) and time.time() - float(state.get("at") or 0) < ALIVE else None

    def ask(self, op: str, timeout: float | None = None, **fields) -> dict:
        name = uuid.uuid4().hex
        req, res = os.path.join(self.spool, name + ".req.json"), os.path.join(self.spool, name + ".res.json")
        try:
            with open(req + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"op": op, **fields}, f)
            os.replace(req + ".tmp", req)  # the relay only reads whole requests
        except OSError as e:
            raise DownloadStationError(f"muthur couldn't write to the relay's folder ({e.strerror or e}).") from e
        end = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < end:
            try:
                with open(res, encoding="utf-8") as f:
                    body = json.load(f)
            except (OSError, ValueError):
                time.sleep(0.2)
                continue
            try:
                os.remove(res)
            except OSError:
                pass
            if not body.get("ok"):
                raise DownloadStationError(body.get("error") or "The relay said no.")
            return body
        try:
            os.remove(req)
        except OSError:
            pass
        raise DownloadStationError("The relay didn't answer. Is the muthur-relay container running?")

    def tasks(self) -> list[dict]:
        return self.ask("list")["tasks"]

    def _delete(self, ids: list[str]) -> None:
        failed = self.ask("delete", ids=ids).get("failed") or []
        if failed:
            raise DownloadStationError(f"Download Station didn't remove {len(failed)} of the tasks.")

    def update_progress(self) -> dict | None:
        try:
            with open(os.path.join(self.spool, "update.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None


class DownloadStation(_Tasks):
    def __init__(self, url: str, user: str, password: str, timeout: float = 15):
        self.base = url.rstrip("/") + "/webapi/"
        self.user, self.password, self.timeout = user, password, timeout
        self.sid: str | None = None

    def _get(self, path: str, post: bool = False, **params) -> dict:
        """post: send the fields in the body, not the URL (the login: a password in a URL ends up in logs)."""
        try:
            # Certificates are checked: the account's password must not go to a machine posing as the NAS.
            if post:
                r = requests.post(self.base + path, data=params, timeout=self.timeout)
            else:
                r = requests.get(self.base + path, params=params, timeout=self.timeout)
            r.raise_for_status()
            body = r.json()
        except requests.exceptions.SSLError as e:
            raise DownloadStationError(f"The NAS's certificate at {self.base} isn't trusted. Use the NAS's http:// address "
                                       "on your own network, or give DSM a trusted certificate.") from e
        except (requests.RequestException, ValueError) as e:
            raise DownloadStationError(f"The NAS didn't answer at {self.base} ({type(e).__name__}).") from e
        if not body.get("success"):
            code = (body.get("error") or {}).get("code")
            raise DownloadStationError(AUTH_ERRORS.get(int(code or 0), f"Download Station answered with error {code}.") if path == "entry.cgi"
                                       else f"Download Station answered with error {code}.")
        return body.get("data") or {}

    def login(self) -> None:
        # Synology's guide shows the login as a GET; DSM's entry.cgi takes the same fields as a form POST
        # (checked on DSM 7.3 with SYNO.API.Info), which keeps the password out of URLs and DSM's logs.
        data = self._get("entry.cgi", post=True, api="SYNO.API.Auth", version=7, method="login", account=self.user,
                         passwd=self.password, session="DownloadStation", format="sid")
        self.sid = data.get("sid")

    def tasks(self) -> list[dict]:
        if not self.sid:
            self.login()
        data = self._get("DownloadStation/task.cgi", api="SYNO.DownloadStation.Task", version=1, method="list",
                         additional="detail,transfer", _sid=self.sid)
        out = []
        for t in data.get("tasks", []):
            add = t.get("additional") or {}
            size, got = t.get("size") or 0, (add.get("transfer") or {}).get("size_downloaded")
            out.append({"id": t["id"], "title": t.get("title"), "status": t.get("status"), "destination": (add.get("detail") or {}).get("destination"),
                        "progress": round(100 * got / size) if isinstance(got, int) and size else None})
        return out

    def _delete(self, ids: list[str]) -> None:
        self._get("DownloadStation/task.cgi", api="SYNO.DownloadStation.Task", version=1, method="delete",
                  id=",".join(ids), force_complete="false", _sid=self.sid)

    def check(self) -> dict:
        try:
            self.login()
        except DownloadStationError as e:
            return {"connected": False, "problem": str(e)}
        return super().check()
