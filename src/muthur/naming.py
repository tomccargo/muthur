"""Target names for the library (ARCHITECTURE.md §6). Pure functions, no file access."""
from __future__ import annotations

import re

# Original titles are kept for these languages (ISO 639-1); others get the English title.
LATIN_SCRIPT = {
    "af", "ca", "cs", "cy", "da", "de", "en", "es", "et", "eu", "fi", "fr", "ga", "gl", "hr", "hu", "id", "is",
    "it", "lt", "lv", "ms", "mt", "nb", "nl", "nn", "no", "pl", "pt", "ro", "sk", "sl", "sq", "sv", "sw", "tl",
    "tr", "vi",
}

_ILLEGAL = re.compile(r'[<>"|?*\x00-\x1f]')


def safe(name: str) -> str:
    """A title that is valid as a file or folder name on Windows, SMB and Linux."""
    s = name.replace(":", " -").replace("/", "-").replace("\\", "-")
    s = _ILLEGAL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(". ")


def display_title(title: str, original_title: str | None, original_language: str | None,
                  keep_original: set[str] = LATIN_SCRIPT) -> str:
    """The title rule: original title for Latin-script languages, otherwise the English title."""
    if original_title and original_language and original_language in keep_original:
        return original_title
    return title


def episode_code(season: int, episodes: list[int]) -> str:
    first = f"S{season:02d}E{episodes[0]:02d}"
    return first + "".join(f"-E{e:02d}" for e in episodes[1:])


def episode_path(show: str, year: int | None, season: int, episodes: list[int], episode_title: str | None, ext: str) -> str:
    """'Foundation (2021)/Season 01/Foundation (2021) - S01E01 - The Emperor's Peace.mkv'."""
    show_dir = safe(f"{show} ({year})" if year else show)
    season_dir = "Specials" if season == 0 else f"Season {season:02d}"
    name = f"{show_dir} - {episode_code(season, episodes)}"
    if episode_title:
        name += f" - {safe(episode_title)}"
    return f"{show_dir}/{season_dir}/{name}{ext.lower()}"


def movie_path(title: str, year: int | None, ext: str, part: int | None = None) -> str:
    """'Aguirre, der Zorn Gottes (1972)/Aguirre, der Zorn Gottes (1972).mkv'."""
    base = safe(f"{title} ({year})" if year else title)
    suffix = f" - cd{part}" if part else ""
    return f"{base}/{base}{suffix}{ext.lower()}"
