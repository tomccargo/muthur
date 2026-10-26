"""After applying fixes only what they touched is checked again (decided 26 Oct): seconds instead of minutes."""
import time

from test_health import FakeTmdb, env  # noqa: F401  (the Health fixture)


def wait(c):
    for _ in range(400):
        job = c.get("/api/jobs/current").json()
        if not job or not job["running"]:
            return job
        time.sleep(0.05)


def test_applying_checks_only_what_the_fixes_touched(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from muthur.web import Config, create_app

    tmp, _, _ = env
    for k, v in {"MUTHUR_CONFIG": tmp / "config", "MUTHUR_DOWNLOADS": tmp / "dl", "MUTHUR_TV": tmp / "TV", "MUTHUR_FILM": tmp / "Film",
                 "MUTHUR_QUARANTINE": tmp / "_q", "TMDB_READ_TOKEN": "x", "MUTHUR_AUTH": "0"}.items():
        monkeypatch.setenv(k, str(v))
    c = TestClient(create_app(Config(dotenv=False), tmdb_factory=lambda token, path: FakeTmdb()))
    c.post("/api/fixes/check")
    wait(c)
    before = c.get("/api/fixes").json()["fixes"]
    assert before["leftovers"]["count"] == 1 and before["episode-nfos"]["count"] > 0
    c.post("/api/fixes/apply", json={"kinds": ["leftovers"]})  # the junk file in Some Show
    job = wait(c)
    after = c.get("/api/fixes").json()["fixes"]
    assert "leftovers" not in after or after["leftovers"]["count"] == 0  # done, so gone from the list
    assert after["episode-nfos"]["count"] == before["episode-nfos"]["count"]  # the rest stays as it was
    assert job["step"] == "Checking what the fixes changed" and job["total"] == 1  # one show read again, not all
    assert not (tmp / "TV" / "Some Show" / "Season 01" / "Downloaded from site.txt").exists()
