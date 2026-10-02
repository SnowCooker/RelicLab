"""Prove that the configured test socket guard blocks network creation."""

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_socket_guard(socket_disabled: None) -> None:
    with pytest.warns(UserWarning, match="socket.socket"), pytest.raises(SocketBlockedError):
        socket.socket()
