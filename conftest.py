"""Pytest-wide fail-closed guard for the core offline CI suite."""

from __future__ import annotations

import pytest

from ci.offline_guard import install

pytest_plugins = ("ci.zero_skip",)


@pytest.fixture(autouse=True)
def block_network():
    """Reinstall the policy before each test in case a test patched a client."""
    install()
