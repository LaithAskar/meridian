"""Optional pytest policy that turns any skipped test into a suite failure."""

from __future__ import annotations

import os

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.environ.get("MERIDIAN_FAIL_ON_SKIP") != "1":
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter is not None else []
    if skipped:
        reporter.write_sep("=", f"ERROR: {len(skipped)} skipped test(s) are forbidden in Meridian CI")
        if exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
