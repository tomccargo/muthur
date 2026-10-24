"""Title normalisation and similarity."""
import re
import unicodedata

from rapidfuzz import fuzz

_ARTICLES = re.compile(r"^(the|a|an|de|het|een|le|la|les|l|der|die|das|il|lo|el|los|las)\s+")


def normalize(title: str) -> str:
    """Lower-case, strip accents and punctuation, unify '&'. 'Schitt's Creek' -> 'schitts creek'."""
    s = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"['’`´]", "", s)
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_article(norm: str) -> str:
    return _ARTICLES.sub("", norm)


def similarity(a: str, b: str) -> float:
    """0..1. Exact after normalisation (with or without a leading article) counts as 1."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb or strip_article(na) == strip_article(nb):
        return 1.0
    if na.replace(" ", "") == nb.replace(" ", ""):
        return 0.98
    return fuzz.ratio(na, nb) / 100.0


def best_similarity(query: str, titles) -> float:
    return max((similarity(query, t) for t in titles if t), default=0.0)
