from muthur.naming import display_title, episode_path, movie_path, safe


def test_safe_replaces_colon_and_illegal_characters():
    assert safe("Mission: Impossible - Rogue Nation") == "Mission - Impossible - Rogue Nation"
    assert safe('What "Is" This?') == "What Is This"
    assert safe("Ends with dot.") == "Ends with dot"


def test_title_rule_keeps_latin_script_originals():
    assert display_title("Aguirre, the Wrath of God", "Aguirre, der Zorn Gottes", "de") == "Aguirre, der Zorn Gottes"
    assert display_title("Spirited Away", "千と千尋の神隠し", "ja") == "Spirited Away"
    assert display_title("Some Film", None, None) == "Some Film"


def test_episode_path():
    assert episode_path("Some Show", 2021, 1, [1], "The Emperor's Peace", ".MKV") == \
        "Some Show (2021)/Season 01/Some Show (2021) - S01E01 - The Emperor's Peace.mkv"
    assert episode_path("Some Show", 2021, 1, [1, 2], None, ".mkv") == \
        "Some Show (2021)/Season 01/Some Show (2021) - S01E01-E02.mkv"
    assert episode_path("Some Show", None, 0, [3], "Christmas", ".mp4") == \
        "Some Show/Specials/Some Show - S00E03 - Christmas.mp4"


def test_movie_path():
    assert movie_path("Some Film", 1972, ".mkv") == "Some Film (1972)/Some Film (1972).mkv"
    assert movie_path("Some Film", 2004, ".avi", part=2) == "Some Film (2004)/Some Film (2004) - cd2.avi"
