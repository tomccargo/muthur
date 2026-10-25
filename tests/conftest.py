import pytest


@pytest.fixture(autouse=True)
def no_scheduler(monkeypatch):
    """Apps built in tests don't start the weekly IMDb refresh."""
    monkeypatch.setenv("MUTHUR_SCHEDULER", "0")
