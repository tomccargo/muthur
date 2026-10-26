"""Shows whose IMDb data isn't downloaded are found by Health, and subtitle languages are read from names."""
from muthur.index import _sub_langs
from test_health import env  # noqa: F401  (the Health fixture: one show with IMDb data, one without)


def test_subtitle_languages_come_from_the_names():
    files = ["x.mkv", "x.en.srt", "x.English.forced.srt", "x.nl.sdh.srt", "x.srt", "xy.fr.srt"]
    assert _sub_langs("x", files) == ["EN", "NL", "SUB"]  # EN once; 'xy.fr.srt' belongs to another video


def test_a_download_shows_its_megabytes_on_the_job():
    import io

    from muthur.imdb import Imdb, _Counted

    class Job:
        step, total, done = None, 0, 0

        def begin(self, step, total):
            self.step, self.total, self.done = step, total, 0

    body = b"x" * 3_200_000
    imdb = Imdb.__new__(Imdb)  # only the download part: no database needed
    imdb.base, imdb.opener = "", lambda url: _Counted(io.BytesIO(body), size=len(body))
    job = Job()
    stream = imdb._fetch("title.ratings.tsv.gz", "Downloading IMDb’s scores", job)
    assert (job.step, job.total, job.done) == ("Downloading IMDb’s scores (3 MB)", 3, 0)
    while stream.read(65536):
        pass
    assert job.done == 3  # the bar went along with the bytes


def test_a_show_without_imdb_data_is_a_fix(env):  # noqa: F811
    _, health, plan = env
    have = health.imdb.shows_with_data()
    assert "tt100" in have
    missing = [x["path"] for x in plan["fixes"]["imdb-data"]]
    assert missing == ["TV/Other Show (2019)"]  # Some Show's data is there; Other Show's ID came from TMDB, its data didn't
