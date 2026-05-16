"""
Tests for backtest/notebooks/export_html.py.

Unit tests (TestFindRepoRoot, TestNotebookPath, TestDefaultOutputPath,
TestExportMissingDeps) are fast and offline.

Integration tests (TestExportIntegration) execute the full notebook and
verify the resulting HTML.  They take ~20-40 s and require nbconvert,
nbformat, ipykernel, matplotlib, and pandas to be installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backtest.notebooks.export_html import (
    default_output_path,
    export,
    find_repo_root,
    notebook_path,
)


def _require_notebook_env(reason: str = "") -> None:
    """Skip the calling test if nbconvert or a python3 kernel is unavailable.

    The class-scoped fixture and standalone tests that actually execute the
    notebook call this at the top so they skip gracefully in environments where
    either nbconvert is absent or the kernel spec hasn't been registered yet
    (e.g. a fresh cloud container where `python -m ipykernel install --user`
    hasn't been run).  The error from a missing kernel is a RuntimeError /
    NoSuchKernel deep inside nbclient — not an ImportError — so importorskip
    alone is insufficient.
    """
    pytest.importorskip("nbconvert", reason="nbconvert not installed")
    try:
        from jupyter_client.kernelspec import KernelSpecManager
        KernelSpecManager().get_kernel_spec("python3")
    except Exception:
        pytest.skip(
            "python3 kernel spec not registered; "
            "run: python -m ipykernel install --user --name python3"
            + (f" ({reason})" if reason else "")
        )


# ---------------------------------------------------------------------------
# TestFindRepoRoot
# ---------------------------------------------------------------------------


class TestFindRepoRoot:
    def test_returns_path_object(self):
        root = find_repo_root()
        assert isinstance(root, Path)

    def test_result_contains_backtest_dir(self):
        root = find_repo_root()
        assert (root / "backtest").is_dir()

    def test_works_from_file_inside_repo(self):
        # Pass a file path — function should walk up from its parent.
        root = find_repo_root(Path(__file__))
        assert (root / "backtest").is_dir()

    def test_works_from_nested_subdir(self):
        # Pass a directory two levels inside the repo.
        nested = find_repo_root() / "backtest" / "notebooks"
        root = find_repo_root(nested)
        assert (root / "backtest").is_dir()

    def test_raises_when_not_found(self, tmp_path):
        # tmp_path is in /tmp/... — no ancestor has a backtest/ dir.
        with pytest.raises(FileNotFoundError, match="backtest"):
            find_repo_root(tmp_path)

    def test_result_is_consistent(self):
        # Two calls should return the same root.
        assert find_repo_root() == find_repo_root()


# ---------------------------------------------------------------------------
# TestNotebookPath
# ---------------------------------------------------------------------------


class TestNotebookPath:
    def test_returns_ipynb_extension(self):
        root = find_repo_root()
        assert notebook_path(root).suffix == ".ipynb"

    def test_file_exists_on_disk(self):
        root = find_repo_root()
        assert notebook_path(root).exists()

    def test_is_valid_nbformat4_json(self):
        root = find_repo_root()
        data = json.loads(notebook_path(root).read_text(encoding="utf-8"))
        assert data["nbformat"] == 4
        assert isinstance(data["cells"], list)
        assert len(data["cells"]) > 0


# ---------------------------------------------------------------------------
# TestDefaultOutputPath
# ---------------------------------------------------------------------------


class TestDefaultOutputPath:
    def test_returns_html_extension(self):
        root = find_repo_root()
        assert default_output_path(root).suffix == ".html"

    def test_is_inside_notebooks_dir(self):
        root = find_repo_root()
        out = default_output_path(root)
        assert out.parent.name == "notebooks"

    def test_is_absolute(self):
        root = find_repo_root()
        assert default_output_path(root).is_absolute()

    def test_stem_is_results(self):
        root = find_repo_root()
        assert default_output_path(root).stem == "results"


# ---------------------------------------------------------------------------
# TestExportMissingDeps
# ---------------------------------------------------------------------------


class TestExportMissingDeps:
    """Verify that export() raises RuntimeError when nbconvert is absent."""

    def test_raises_runtime_error(self, monkeypatch):
        # Simulate nbconvert not being installed by hiding it from sys.modules.
        # Setting sys.modules[name] = None causes ImportError on next import.
        monkeypatch.setitem(sys.modules, "nbformat", None)
        monkeypatch.setitem(sys.modules, "nbconvert", None)
        with pytest.raises(RuntimeError, match="nbconvert is not installed"):
            export()

    def test_error_message_has_install_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "nbformat", None)
        monkeypatch.setitem(sys.modules, "nbconvert", None)
        with pytest.raises(RuntimeError, match="pip install"):
            export()


# ---------------------------------------------------------------------------
# TestExportIntegration  (executes the notebook — ~20-40 s)
# ---------------------------------------------------------------------------


class TestExportIntegration:
    """Run the full export pipeline and validate the HTML artefact."""

    @pytest.fixture(scope="class")
    def exported_html(self, tmp_path_factory):
        """Execute the notebook once and return (path, content) for all tests."""
        _require_notebook_env()
        out = tmp_path_factory.mktemp("html") / "results.html"
        export(output=out, show_input=False, timeout=120)
        return out, out.read_text(encoding="utf-8")

    def test_html_file_is_created(self, exported_html):
        out, _ = exported_html
        assert out.exists()

    def test_html_file_is_nontrivial(self, exported_html):
        out, _ = exported_html
        # A minimal rendered notebook is at least 50 KB.
        assert out.stat().st_size > 50_000

    def test_html_contains_title(self, exported_html):
        _, html = exported_html
        assert "Meridian Backtester" in html

    def test_html_contains_full_window_section(self, exported_html):
        _, html = exported_html
        assert "Full-Window Metrics" in html

    def test_html_contains_disclosures(self, exported_html):
        _, html = exported_html
        assert "Honest Disclosures" in html

    def test_html_contains_equity_curve_section(self, exported_html):
        _, html = exported_html
        assert "Equity Curves" in html

    def test_html_contains_embedded_image(self, exported_html):
        _, html = exported_html
        # Images should be embedded as base64 data URIs (not linked externally).
        assert "data:image/" in html

    def test_code_cells_excluded_by_default(self, exported_html):
        _, html = exported_html
        # When show_input=False (default), code cells are excluded.  The
        # Pygments-rendered form of module names (e.g. 'nn">matplotlib') is
        # the reliable indicator that code is present in the HTML.
        assert 'nn">matplotlib' not in html

    def test_show_input_includes_code(self, tmp_path):
        _require_notebook_env()
        out = tmp_path / "with_input.html"
        export(output=out, show_input=True, timeout=120)
        html = out.read_text(encoding="utf-8")
        # nbconvert syntax-highlights code via Pygments, so module names like
        # "matplotlib" appear inside a <span class="nn">...</span> rather than
        # as raw text.  Check for the Pygments-rendered form.
        assert 'nn">matplotlib' in html

    def test_custom_output_path_respected(self, tmp_path):
        _require_notebook_env()
        custom = tmp_path / "custom_name.html"
        result = export(output=custom, timeout=120)
        assert result == custom
        assert custom.exists()

    def test_return_value_equals_output_path(self, tmp_path):
        _require_notebook_env()
        out = tmp_path / "ret_check.html"
        returned = export(output=out, timeout=120)
        assert returned == out

    def test_is_valid_html(self, exported_html):
        _, html = exported_html
        # Basic structural checks for well-formed HTML.
        assert html.strip().startswith("<!DOCTYPE html>") or "<html" in html
        assert "</html>" in html
