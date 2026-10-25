import pytest


@pytest.fixture(autouse=True)
def no_scheduler(monkeypatch, tmp_path):
    """Apps built in tests don't start the weekly IMDb refresh."""
    monkeypatch.setenv("MUTHUR_SCHEDULER", "0")
    monkeypatch.setenv("MUTHUR_AUTH", "0")  # signing in has its own tests (test_auth.py)
    # A test never writes outside its own folder: the default quarantine (/data/...) is C:\data on Windows.
    monkeypatch.setenv("MUTHUR_QUARANTINE", str(tmp_path / "_muthur-quarantine"))
