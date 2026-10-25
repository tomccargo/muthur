"""Kodi re-reads NFOs muthur changed, whatever the library folders are called."""
import os

from muthur.kodi import Kodi, folder_name


class FakeKodi(Kodi):
    def __init__(self):
        super().__init__("box")
        self.refreshed = []

    def call(self, method, params=None):
        self.calls = getattr(self, "calls", []) + [method]
        if method == "Files.GetSources":
            return {"sources": [{"file": "smb://nas/media/Series/"}, {"file": "smb://nas/media/Movies/"}]}
        if method == "VideoLibrary.GetTVShows":
            return {"tvshows": [{"tvshowid": 3, "file": "smb://nas/media/Series/Ghosts (2021)/"}]}
        if method == "VideoLibrary.GetEpisodes":
            return {"episodes": [{"episodeid": 30, "file": "smb://nas/media/Series/Ghosts (2021)/Season 01/Ghosts (2021) - S01E01.mkv"}]}
        if method == "VideoLibrary.GetMovies":
            return {"movies": [{"movieid": 40, "file": "smb://nas/media/Movies/Dune (2021)/Dune (2021).mkv"}]}
        self.refreshed.append((method, params))
        return "OK"


def test_sources_are_found_by_the_folders_own_names(tmp_path):
    tv, film = str(tmp_path / "Series"), str(tmp_path / "Movies")
    k = FakeKodi()
    paths = [os.path.join(tv, "Ghosts (2021)", "tvshow.nfo"),
             os.path.join(tv, "Ghosts (2021)", "Season 01", "Ghosts (2021) - S01E01.nfo"),
             os.path.join(film, "Dune (2021)", "Dune (2021).nfo")]
    assert k.refresh_files(paths, {"TV": tv, "Film": film}) == {"refreshed": 3, "notInKodi": 0}
    assert [m for m, _ in k.refreshed] == ["VideoLibrary.RefreshTVShow", "VideoLibrary.RefreshEpisode", "VideoLibrary.RefreshMovie"]
    assert k.source_prefix(folder_name(tv + "/")) == "smb://nas/media/Series/"


def test_a_big_batch_reads_the_show_list_once_and_reports_progress(tmp_path):
    tv, film = str(tmp_path / "Series"), str(tmp_path / "Movies")
    k = FakeKodi()
    paths = [os.path.join(tv, "Ghosts (2021)", "tvshow.nfo")] * 3
    seen = []
    k.refresh_files(paths, {"TV": tv, "Film": film}, lambda done, total: seen.append((done, total)))
    assert k.calls.count("VideoLibrary.GetTVShows") == 1
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_kodi_going_away_is_not_reported_as_missing_items(tmp_path):
    import requests

    class Away(FakeKodi):
        def call(self, method, params=None):
            raise requests.exceptions.ConnectionError("refused")

    tv = str(tmp_path / "Series")
    paths = [os.path.join(tv, "Ghosts (2021)", "Season 01", f"Ghosts (2021) - S01E0{n}.nfo") for n in (1, 2, 3)]
    assert Away().refresh_files(paths, {"TV": tv, "Film": str(tmp_path / "Movies")}) == {"refreshed": 0, "notInKodi": 0, "kodiAway": 3}
