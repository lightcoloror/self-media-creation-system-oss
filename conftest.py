"""Offline public-workspace tests: no DNS or socket connections."""
import socket
import pytest

@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Network is forbidden in public workspace contract tests')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
