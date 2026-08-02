"""Small networking helpers used by the launcher."""

from __future__ import annotations

import socket

__all__ = ["is_port_available", "pick_server_port"]


def _socket_family(host: str) -> int:
    """Best-effort socket family for a bind target."""
    return socket.AF_INET6 if ":" in host else socket.AF_INET


def is_port_available(host: str, port: int) -> bool:
    """Return ``True`` when ``host:port`` can be bound right now."""
    family = _socket_family(host)
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_server_port(host: str, preferred_port: int) -> int:
    """Return the preferred port, or a free ephemeral fallback when needed."""
    if is_port_available(host, preferred_port):
        return preferred_port

    family = _socket_family(host)
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
