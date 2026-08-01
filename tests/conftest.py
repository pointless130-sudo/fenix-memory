"""Suite-wide guards: repo importable, and NO NETWORK — the whole suite
must run with no network and no API key (brief §5, §8.9)."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _NetworkBlocked(Exception):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkBlocked("network access attempted during test suite")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


FIXED_CLOCK = "2026-07-31T00:00:00+00:00"


@pytest.fixture
def clock():
    return lambda: FIXED_CLOCK
