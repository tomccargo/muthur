"""Synology Download Station: remove a finished task once muthur has moved its files (ARCHITECTURE.md §16).

Uses the Web API in Synology's Download Station developer guide: SYNO.API.Auth (entry.cgi) to log in
with a DSM account that has Download Station rights only, and SYNO.DownloadStation.Task (task.cgi)
to list and delete tasks. A task is only removed after its download was moved successfully, never
before, and only when it is finished or seeding.
"""
from __future__ import annotations

import requests

DONE = {"finished", "seeding"}


class DownloadStationError(Exception):
    """A sentence for the reader."""


AUTH_ERRORS = {400: "The account or password is wrong.", 401: "That account is disabled.", 402: "That account may not use Download Station.",
               403: "That account uses two-step verification; give muthur an account without it.", 407: "The NAS blocked this address after failed logins."}


class DownloadStation:
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
                         additional="detail", _sid=self.sid)
        return [{"id": t["id"], "title": t.get("title"), "status": t.get("status"),
                 "destination": ((t.get("additional") or {}).get("detail") or {}).get("destination")} for t in data.get("tasks", [])]

    def remove_finished(self, titles: set[str]) -> dict:
        """Delete the finished or seeding tasks with these titles (the names of downloads muthur moved)."""
        matches = [t for t in self.tasks() if t["title"] in titles]
        done = [t for t in matches if t["status"] in DONE]
        if done:
            self._get("DownloadStation/task.cgi", api="SYNO.DownloadStation.Task", version=1, method="delete",
                      id=",".join(t["id"] for t in done), force_complete="false", _sid=self.sid)
        return {"removed": [t["title"] for t in done], "notFinished": [t["title"] for t in matches if t["status"] not in DONE]}

    def check(self) -> dict:
        try:
            self.login()
            return {"connected": True, "tasks": len(self.tasks())}
        except DownloadStationError as e:
            return {"connected": False, "problem": str(e)}
