"""Signing in to muthur's web UI (ARCHITECTURE.md §14).

One password, chosen on the first visit and kept as an scrypt hash in muthur's database. Signing in
gives the browser a random session cookie (HttpOnly, SameSite=Strict) that lasts 30 days of use.
Requests that change something must come from muthur's own page: when the browser says a request
comes from another site (Sec-Fetch-Site, or else Origin), it is refused, so a web page elsewhere
can't press muthur's buttons. Forgotten password: `muthur password` in the container sets a new one.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlsplit

COOKIE = "muthur_session"
SESSION_SECONDS = 30 * 86400
MIN_LENGTH = 8
TRIES, TRY_WINDOW = 5, 300  # wrong passwords per address before a pause, and the pause
SCHEMA = "CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, created REAL NOT NULL, used REAL NOT NULL);"


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=64 << 20, dklen=32).hex()


def _digest(token: str) -> str:
    """Sessions are stored hashed: a copy of the database doesn't sign anyone in."""
    return hashlib.sha256(token.encode()).hexdigest()


def same_site(headers) -> bool:
    """False when the browser says a request comes from another site. Tools without a browser send
    neither header and are let through; they still need the session cookie."""
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = headers.get("origin")
    return origin is None or urlsplit(origin).netloc == headers.get("host")


class Auth:
    def __init__(self, store, required: bool = True):
        self.store, self.required = store, required
        self.failures: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        with store.lock:
            store.db.execute(SCHEMA)
            store.db.commit()

    # -- the password ------------------------------------------------------------------
    def is_set(self) -> bool:
        return bool(self.store.get("auth.password"))

    def set_password(self, password: str) -> None:
        """A new password signs every browser out."""
        if len(password) < MIN_LENGTH:
            raise ValueError(f"Use at least {MIN_LENGTH} characters.")
        salt, n, r, p = secrets.token_bytes(16), 2 ** 14, 8, 1
        self.store.put("auth.password", {"salt": salt.hex(), "n": n, "r": r, "p": p, "hash": _scrypt(password, salt, n, r, p)})
        with self.store.lock:
            self.store.db.execute("DELETE FROM sessions")
            self.store.db.commit()

    def check(self, password: str) -> bool:
        h = self.store.get("auth.password")
        if not h:
            return False
        return hmac.compare_digest(_scrypt(password, bytes.fromhex(h["salt"]), h["n"], h["r"], h["p"]), h["hash"])

    def allowed(self, address: str) -> bool:
        """False after too many wrong passwords from one address in a short time."""
        with self.lock:
            recent = [t for t in self.failures.get(address, []) if time.time() - t < TRY_WINDOW]
            self.failures[address] = recent
            return len(recent) < TRIES

    def failed(self, address: str) -> None:
        with self.lock:
            self.failures.setdefault(address, []).append(time.time())

    # -- sessions -------------------------------------------------------------------------
    def start_session(self) -> str:
        token, now = secrets.token_urlsafe(32), time.time()
        with self.store.lock:
            self.store.db.execute("DELETE FROM sessions WHERE used < ?", (now - SESSION_SECONDS,))
            self.store.db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (_digest(token), now, now))
            self.store.db.commit()
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        key, now = _digest(token), time.time()
        with self.store.lock:
            row = self.store.db.execute("SELECT used FROM sessions WHERE token = ?", (key,)).fetchone()
            if not row or now - row[0] > SESSION_SECONDS:
                return False
            if now - row[0] > 3600:  # keep the session alive while it is used, without a write per request
                self.store.db.execute("UPDATE sessions SET used = ? WHERE token = ?", (now, key))
                self.store.db.commit()
        return True

    def end_session(self, token: str | None) -> None:
        if token:
            with self.store.lock:
                self.store.db.execute("DELETE FROM sessions WHERE token = ?", (_digest(token),))
                self.store.db.commit()
