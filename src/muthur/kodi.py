"""Kodi JSON-RPC over HTTP. Milestone 2 only reads: is Kodi there, and which version."""
from __future__ import annotations

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
