"""Shared, verified HTTPS configuration for Supabase adapters."""

from __future__ import annotations

import ssl
from functools import lru_cache

import certifi


@lru_cache(maxsize=1)
def supabase_ssl_context() -> ssl.SSLContext:
    """Use a bundled CA store when the host Python trust store is incomplete."""

    return ssl.create_default_context(cafile=certifi.where())
