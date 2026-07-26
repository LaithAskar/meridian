"""Isolated regression tests for Meridian's zero-skip pytest plugin."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from ci.zero_skip import pytest_sessionfinish


NON_SUCCESS_EXIT_CODES = [
    pytest.ExitCode.TESTS_FAILED,
    pytest.ExitCode.INTERRUPTED,
    pytest.ExitCode.INTERNAL_ERROR,
    pytest.ExitCode.USAGE_ERROR,
    pytest.ExitCode.NO_TESTS_COLLECTED,
]
ALL_EXIT_CODES = [pytest.ExitCode.OK, *NON_SUCCESS_EXIT_CODES]


def _session(exitstatus: pytest.ExitCode, *, skipped: int):
    reporter = Mock()
    reporter.stats = {"skipped": [object()] * skipped}
    pluginmanager = Mock()
    pluginmanager.get_plugin.return_value = reporter
    session = SimpleNamespace(
        config=SimpleNamespace(pluginmanager=pluginmanager),
        exitstatus=exitstatus,
    )
    return cast(pytest.Session, session), reporter


def test_success_with_skip_becomes_test_failure(monkeypatch):
    monkeypatch.setenv("MERIDIAN_FAIL_ON_SKIP", "1")
    session, reporter = _session(pytest.ExitCode.OK, skipped=1)

    pytest_sessionfinish(session, pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    reporter.write_sep.assert_called_once()


@pytest.mark.parametrize("exitstatus", NON_SUCCESS_EXIT_CODES)
def test_skip_preserves_pre_existing_non_success_status(monkeypatch, exitstatus):
    monkeypatch.setenv("MERIDIAN_FAIL_ON_SKIP", "1")
    session, reporter = _session(exitstatus, skipped=1)

    pytest_sessionfinish(session, exitstatus)

    assert session.exitstatus == exitstatus
    reporter.write_sep.assert_called_once()


@pytest.mark.parametrize("exitstatus", ALL_EXIT_CODES)
def test_zero_skips_preserves_status(monkeypatch, exitstatus):
    monkeypatch.setenv("MERIDIAN_FAIL_ON_SKIP", "1")
    session, reporter = _session(exitstatus, skipped=0)

    pytest_sessionfinish(session, exitstatus)

    assert session.exitstatus == exitstatus
    reporter.write_sep.assert_not_called()
