"""The UI checks of DESIGN.md §10: every page, at 375 and 1280 px, in both themes, with sample data.

Fails on page or console errors, a page that scrolls sideways, more than one primary button (or none on
a page that has an action), container paths or code words on screen, corners rounder than 12 px (pills
excepted), and animations while reduced motion is asked for.
Skipped when Playwright or the built UI (web/dist) isn't there.
"""
import os
import re
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
if not (DIST / "index.html").is_file():
    pytest.skip("the UI isn't built (npm run build in web/)", allow_module_level=True)

import uvicorn  # noqa: E402

from muthur.web import Config, create_app  # noqa: E402
from test_review import FakeTmdb, _old  # noqa: E402

PAGES = {  # path -> must it have exactly one primary button?
    "/": True, "/inbox": True, "/review": True, "/library": None, "/library?folder=The+Office+%28US%29": False,
    "/duplicates": True, "/health": True, "/history": False, "/settings": True,
}
CODE_WORDS = re.compile(r"/data/|absolute-number|broken-episode-number|no-episode-number|looks-like-movie|other-episode"
                        r"|first_air_date|tmdb_id|\bundefined\b|\bNaN\b|\[object Object\]")


def wait_job(client_get):
    for _ in range(200):
        job = client_get("/api/jobs/current")
        if not job or not job["running"]:
            return
        time.sleep(0.05)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ui")
    # A long folder name without hyphens: a path on screen has to wrap anywhere, not only at a '-'.
    dl, tv, film = tmp / "afinisheddownloadsfolderwithaverylongnamewithoutanyhyphens" / "complete", tmp / "TV", tmp / "Film"
    season = tv / "The Office (US)" / "Season 04"
    season.mkdir(parents=True)
    (tv / "The Office (US)" / "tvshow.nfo").write_text('<tvshow><title>The Office</title><uniqueid type="tmdb">2316</uniqueid></tvshow>')
    for n, t in ((13, "Dinner Party"), (14, "The Chair Model")):
        (season / f"The Office S04E{n} - {t} - (2008) - SD.avi").write_bytes(b"x")
    (season / "The Office S04E14 - The Chair Model - (2008) - 480p.mp4").write_bytes(b"xx")  # a duplicate
    (season / "Downloaded from a.very.long.site.name.without.any.spaces.at.all.org.txt").write_text("junk")
    (film / "Solaris (1972)").mkdir(parents=True)
    for name in ("The Office US S04E19 Goodbye Toby Part 2 720p WEB-DL.mkv", "Solaris.720p.BluRay.x264.mkv",
                 "A.Very.Long.Release.Name.Without.Any.Spaces.That.Would.Push.The.Page.Wider.2020.1080p.WEB.mkv"):
        (dl / name).parent.mkdir(parents=True, exist_ok=True)
        (dl / name).write_bytes(b"v" * 100)
        _old(dl / name)
    env = {"MUTHUR_CONFIG": tmp / "config", "MUTHUR_DOWNLOADS": dl, "MUTHUR_TV": tv, "MUTHUR_FILM": film,
           "MUTHUR_QUARANTINE": tmp / "_q", "TMDB_READ_TOKEN": "x", "MUTHUR_WEB": DIST, "MUTHUR_SCHEDULER": "0", "MUTHUR_AUTH": "0"}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    app = create_app(Config(dotenv=False), tmdb_factory=FakeTmdb)
    app.state.store.remember("tv", "The Office", 2316, 2005, "The Office", "The Office (US)", "library")

    from fastapi.testclient import TestClient

    c = TestClient(app)
    get = lambda p: c.get(p).json()  # noqa: E731
    c.post("/api/inbox/scan"), wait_job(get)
    c.post("/api/review/choose", json={"id": "Solaris.720p.BluRay.x264.mkv", "choice": {"kind": "movie", "tmdbId": 9}})
    c.post("/api/apply", json={"ids": ["Solaris.720p.BluRay.x264.mkv"]}), wait_job(get)
    c.post("/api/duplicates/scan"), wait_job(get)
    c.post("/api/fixes/check"), wait_job(get)
    # A Health run in History too: its summary counts fixes instead of listing items (History once crashed on it).
    c.post("/api/fixes/apply", json={"kinds": ["leftovers"]}), wait_job(get)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


CHECKS = """() => {
  const all = [...document.querySelectorAll('body *')];
  const radius = all.map((e) => [e, parseFloat(getComputedStyle(e).borderTopLeftRadius)])
    .filter(([e, r]) => r > 12.5 && r < 990 && !getComputedStyle(e).borderTopLeftRadius.includes('%'))
    .map(([e, r]) => `${e.tagName}.${e.className} ${r}px`);
  return {
    scroll: document.documentElement.scrollWidth - innerWidth,
    primaries: document.querySelectorAll('.btn-primary').length,
    text: document.body.innerText,
    radius: radius.slice(0, 3),
    animations: document.getAnimations().length,
  };
}"""


@pytest.mark.parametrize("width", [375, 1280])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_page(server, browser, width, theme):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme, reduced_motion="reduce")
    ctx.add_init_script(f"try {{ localStorage.setItem('muthur.theme', '{theme}') }} catch (e) {{}}")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(server) else r.abort())  # no TMDB images in tests
    problems = []
    for path, one_primary in PAGES.items():
        page.goto(server + path)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)
        r = page.evaluate(CHECKS)
        where = f"{path} at {width}px, {theme}"
        if r["scroll"] > 0:
            problems.append(f"{where}: scrolls sideways by {r['scroll']}px")
        if one_primary is True and r["primaries"] != 1:
            problems.append(f"{where}: {r['primaries']} primary buttons, expected 1")
        if one_primary is not True and r["primaries"] > 1:
            problems.append(f"{where}: {r['primaries']} primary buttons")
        if m := CODE_WORDS.search(r["text"]):
            problems.append(f"{where}: '{m.group(0)}' on screen")
        if r["radius"]:
            problems.append(f"{where}: corners rounder than 12px: {r['radius']}")
        if r["animations"]:
            problems.append(f"{where}: {r['animations']} animations with reduced motion")
    problems += errors
    ctx.close()
    assert not problems, "\n".join(problems)


def test_clicking_from_the_list_into_a_show_and_back(server, browser):
    """The list and a show are one component: opening a show from the list must render (React error #300 in 0.29.0)."""
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(server) else r.abort())
    page.goto(server + "/library")
    page.wait_for_load_state("networkidle")
    page.click('a[href*="folder="]')
    page.wait_for_selector("text=TV/The Office (US)/")
    page.set_viewport_size({"width": 375, "height": 800})
    page.click('button[aria-label^="Actions for"] >> nth=0')  # an episode's menu: it opens in its row
    page.wait_for_selector("text=Re-read in Kodi")
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0
    page.set_viewport_size({"width": 1280, "height": 800})
    page.click("text=← Library")
    page.wait_for_selector("h1:has-text('Shows and films')")
    page.click("nav.rail >> text=Health")  # its own place in the rail, not a tab under Library
    page.wait_for_selector("h1:has-text('Health')")
    page.set_viewport_size({"width": 375, "height": 800})
    tabs = page.evaluate("[...document.querySelectorAll('.tabbar .tab')].map((t) => [t.innerText.trim(), t.scrollWidth - t.clientWidth])")
    assert [t for t, _ in tabs] == ["Dashboard", "Downloads", "Library", "Health", "History", "Settings"]
    assert all(over <= 0 for _, over in tabs), tabs  # six tabs fit on a phone
    page.close()
    assert not errors, errors


def test_duplicates_have_their_own_panel_and_tile(server, browser):
    """Duplicates were one word inside Tidy up (0.40): now a Dashboard tile that opens them, and a Health panel by name."""
    page = browser.new_page()
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(server) else r.abort())
    page.goto(server + "/health")
    page.wait_for_selector("#duplicates")
    assert "The Office S04E14" in page.inner_text("#duplicates")
    assert "#duplicates" not in page.inner_text("#tidy") if page.query_selector("#tidy") else True
    page.goto(server + "/")
    page.click(".tile:has-text('Duplicates')")
    page.wait_for_selector("h1:has-text('Duplicates')")
    page.goto(server + "/")
    target = page.get_attribute(".tile[href^='/health#']", "href")  # every other tile opens its own panel
    page.click(f".tile[href='{target}']")
    page.wait_for_selector(target.replace("/health", ""))
    assert page.evaluate("location.pathname + location.hash") == target
    page.close()
