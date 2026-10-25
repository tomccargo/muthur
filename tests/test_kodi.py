"""Kodi re-reads NFOs muthur changed, whatever the library folders are called."""
import os

from muthur.kodi import Kodi, folder_name


class FakeKodi(Kodi):
    def __init__(self):
        super().__init__("box")
        self.refreshed = []

    def call(self, method, params=None):
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
