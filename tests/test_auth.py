"""Signing in, refusing other websites, and the other guards of ARCHITECTURE.md §14."""
import pytest
from fastapi.testclient import TestClient

from muthur.auth import Auth
from muthur.shield import Shield, ShieldError
from muthur.store import Store
from muthur.web import Config, create_app


def _app(tmp_path, monkeypatch, auth: bool = True):
    monkeypatch.setenv("MUTHUR_AUTH", "1" if auth else "0")
    for key, sub in (("MUTHUR_CONFIG", "config"), ("MUTHUR_DOWNLOADS", "complete"), ("MUTHUR_TV", "TV"),
                     ("MUTHUR_FILM", "Film"), ("MUTHUR_WEB", "no-web")):
        (tmp_path / sub).mkdir(exist_ok=True)
        monkeypatch.setenv(key, str(tmp_path / sub))
    monkeypatch.delenv("TMDB_READ_TOKEN", raising=False)
    return create_app(Config(dotenv=False))


def test_first_visit_chooses_the_password_then_it_is_asked(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch))
    r = c.get("/api/status")
    assert r.status_code == 401 and r.json()["auth"] == "setup"
    assert c.get("/api/health").status_code == 200  # the container's health check needs no password
    assert c.post("/api/auth/setup", json={"password": "short"}).status_code == 422
    assert c.post("/api/auth/setup", json={"password": "a long password"}).status_code == 200
    assert c.get("/api/status").status_code == 200  # the browser that chose it is signed in
    assert c.post("/api/auth/setup", json={"password": "another one!"}).status_code == 409  # only once

    other = TestClient(c.app)
    assert other.get("/api/status").json()["auth"] == "login"
    assert other.post("/api/auth/login", json={"password": "wrong password"}).status_code == 401
    assert other.post("/api/auth/login", json={"password": "a long password"}).status_code == 200
    assert other.get("/api/status").status_code == 200
    other.post("/api/auth/logout")
    assert other.get("/api/status").status_code == 401


def test_the_cookie_is_httponly_and_strict(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch))
    r = c.post("/api/auth/setup", json={"password": "a long password"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_wrong_passwords_get_a_pause(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch))
    c.post("/api/auth/setup", json={"password": "a long password"})
    other = TestClient(c.app)
    codes = [other.post("/api/auth/login", json={"password": f"guess {n}"}).status_code for n in range(6)]
    assert codes == [401] * 5 + [429]
    assert other.post("/api/auth/login", json={"password": "a long password"}).status_code == 429  # even the right one, for now


def test_a_new_password_signs_everyone_out(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch))
    c.post("/api/auth/setup", json={"password": "a long password"})
    other = TestClient(c.app)
    other.post("/api/auth/login", json={"password": "a long password"})
    assert c.post("/api/auth/password", json={"current": "nope nope", "new": "x" * 10}).status_code == 403
    assert c.post("/api/auth/password", json={"current": "a long password", "new": "a new long password"}).status_code == 200
    assert c.get("/api/status").status_code == 200  # this browser got a new session
    assert other.get("/api/status").status_code == 401


def test_password_reset_from_the_command_line_works_on_the_same_database(tmp_path):
    store = Store(str(tmp_path / "muthur.db"))
    auth = Auth(store)
    auth.set_password("first password")
    token = auth.start_session()
    Auth(Store(str(tmp_path / "muthur.db"))).set_password("second password")
    assert auth.check("second password") and not auth.check("first password")
    assert not auth.valid(token)


@pytest.mark.parametrize("headers", [{"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                                     {"Origin": "http://evil.example"}, {"Origin": "null"}])
def test_changes_from_another_website_are_refused(tmp_path, monkeypatch, headers):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))  # refused even without a password
    assert c.post("/api/history/1/undo", headers=headers).status_code == 403
    assert c.post("/api/inbox/scan", headers=headers).status_code == 403
    assert c.get("/api/status", headers=headers).status_code == 200  # reading is fine; the browser keeps the answer from that site


def test_changes_from_muthurs_own_page_pass(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    for headers in ({"Sec-Fetch-Site": "same-origin"}, {"Origin": "http://testserver"}, {}):
        assert c.put("/api/settings", json={"dryRun": True}, headers=headers).status_code == 200


def test_apply_only_takes_downloads_from_the_inbox(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    c.put("/api/settings", json={"tmdb": {"token": "x"}})
    r = c.post("/api/apply", json={"ids": ["../Film/Dune (2021)"]})
    assert r.status_code == 404


def test_undo_is_refused_in_a_dry_run(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    c.put("/api/settings", json={"dryRun": True})
    assert c.post("/api/history/1/undo", json={}).status_code == 409


def test_a_new_kodi_address_forgets_the_password(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    c.put("/api/settings", json={"kodi": {"host": "192.168.1.20", "user": "kodi", "password": "secret"}})
    assert c.put("/api/settings", json={"kodi": {"host": "192.168.1.20", "user": "kodi"}}).json()["kodi"]["passwordSet"]
    assert not c.put("/api/settings", json={"kodi": {"host": "10.0.0.66"}}).json()["kodi"]["passwordSet"]
    c.put("/api/settings", json={"downloadStation": {"url": "http://nas:5000", "user": "dl", "password": "pw"}})
    assert not c.put("/api/settings", json={"downloadStation": {"url": "http://elsewhere:5000"}}).json()["downloadStation"]["passwordSet"]


def test_the_shield_app_must_be_an_app(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    assert c.put("/api/settings", json={"shield": {"app": "org.xbmc.kodi/.Splash; reboot"}}).status_code == 422
    assert c.put("/api/settings", json={"shield": {"app": "org.xbmc.kodi/.Splash"}}).status_code == 200
    calls = []
    s = Shield("box", 5555, "/cfg", lambda args, home, timeout: calls.append(args) or (0, ""))
    with pytest.raises(ShieldError):
        s.wake_and_start("org.xbmc.kodi/.Splash && reboot", lambda: True)
    assert calls == []  # nothing reached the box


def test_saved_secrets_can_be_forgotten_and_the_language_chosen(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    monkeypatch.setenv("TMDB_READ_TOKEN", "from-the-install")
    s = c.put("/api/settings", json={"tmdb": {"token": "saved-in-muthur", "language": "nl-BE"}}).json()
    assert s["tmdb"]["tokenFrom"] == "settings" and s["tmdb"]["language"] == "nl-BE"
    assert c.put("/api/settings", json={"tmdb": {"forget": True}}).json()["tmdb"]["tokenFrom"] == "install"
    assert c.put("/api/settings", json={"tmdb": {"language": "dutch"}}).status_code == 422
    c.put("/api/settings", json={"downloadStation": {"url": "http://nas:5000", "user": "dl", "password": "pw"}})
    ds = c.put("/api/settings", json={"downloadStation": {"forget": True}}).json()["downloadStation"]
    assert ds == {"url": "", "user": "", "passwordSet": False}
    assert c.put("/api/settings", json={"kodi": {"tcpPort": "9777"}}).json()["kodi"]["tcpPort"] == 9777


def test_migrations_run_once_and_a_new_database_starts_past_them(tmp_path, monkeypatch):
    from muthur import store as store_module

    old = Store(str(tmp_path / "old.db"))  # made before the migration existed
    monkeypatch.setattr(store_module, "MIGRATIONS", ["CREATE TABLE added (x INTEGER);"])
    assert Store(str(tmp_path / "old.db")).migrate() == 1
    assert Store(str(tmp_path / "old.db")).migrate() == 0
    assert Store(str(tmp_path / "new.db")).migrate() == 0  # new: already at the newest schema
    del old


def test_names_are_neutral_until_the_reader_sets_them(tmp_path, monkeypatch):
    c = TestClient(_app(tmp_path, monkeypatch, auth=False))
    assert c.get("/api/status").json()["names"] == {"device": "Kodi device", "nas": "NAS"}
    s = c.put("/api/settings", json={"names": {"device": " Shield ", "nas": "Nostromo"}}).json()
    assert s["names"] == {"device": "Shield", "nas": "Nostromo"}
    assert c.post("/api/kodi/test").json()["problem"] == "Enter the Shield's address first."
    assert c.put("/api/settings", json={"names": {"device": ""}}).json()["names"]["device"] == "Kodi device"
