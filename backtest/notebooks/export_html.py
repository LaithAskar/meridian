"""
Export results.ipynb to self-contained static HTML for the portfolio site.

Usage (from repo root):
    python -m backtest.notebooks.export_html
    python -m backtest.notebooks.export_html --output path/to/output.html
    python -m backtest.notebooks.export_html --show-input

Options:
    --output PATH   Destination HTML file.
                    Default: backtest/notebooks/results.html
    --show-input    Include code cells in the rendered output.
                    Default: code cells are hidden (clean results view).
    --timeout N     Per-cell execution timeout in seconds. Default: 300.

The notebook is executed in the current Python environment, so all backtest
modules and their dependencies must be installed.  Matplotlib figures are
embedded as base64 data URIs, making the output a single portable HTML file
that can be hosted anywhere without serving additional assets.

Requires: nbconvert>=7.0.0  nbformat>=5.9.0  ipykernel>=6.0.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def find_repo_root(start: Path | None = None) -> Path:
    """
    Walk up the directory tree from *start* until finding a directory that
    contains a ``backtest/`` sub-directory (the repo root).

    Parameters
    ----------
    start : Path, optional
        Starting point for the search.  May be a file or directory.
        Defaults to the location of this module (``export_html.py``).

    Raises
    ------
    FileNotFoundError
        If no ancestor directory contains ``backtest/``.
    """
    cur = (start or Path(__file__)).resolve()
    if cur.is_file():
        cur = cur.parent
    while cur != cur.parent:
        if (cur / "backtest").is_dir():
            return cur
        cur = cur.parent
    raise FileNotFoundError(
        "Could not find repo root: no ancestor directory contains backtest/"
    )


def notebook_path(repo_root: Path) -> Path:
    """Absolute path to results.ipynb."""
    return repo_root / "backtest" / "notebooks" / "results.ipynb"


def default_output_path(repo_root: Path) -> Path:
    """Default HTML output path: backtest/notebooks/results.html."""
    return repo_root / "backtest" / "notebooks" / "results.html"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export(
    output: Path | None = None,
    show_input: bool = False,
    timeout: int = 300,
) -> Path:
    """
    Execute ``results.ipynb`` and write self-contained HTML to *output*.

    The notebook is executed with ``allow_errors=True`` so that cells with
    unavailable results (e.g. empty CSVs) still render gracefully — they show
    placeholder text rather than crashing the export.

    Images produced by matplotlib are embedded as base64 data URIs so the
    output HTML has no external dependencies.

    Parameters
    ----------
    output : Path, optional
        Destination file.  Defaults to ``backtest/notebooks/results.html``.
    show_input : bool
        If True, code cells are included in the HTML.  Default False keeps
        the page clean for a portfolio viewer.
    timeout : int
        Per-cell execution timeout in seconds.

    Returns
    -------
    Path
        The path of the written HTML file.

    Raises
    ------
    RuntimeError
        If nbconvert / nbformat / ipykernel are not installed.
    """
    try:
        import nbformat
        from nbconvert import HTMLExporter
        from nbconvert.preprocessors import ExecutePreprocessor
    except ImportError as exc:
        raise RuntimeError(
            "nbconvert is not installed. "
            "Run: pip install nbconvert>=7.0.0 nbformat>=5.9.0 ipykernel>=6.0.0"
        ) from exc

    repo_root = find_repo_root()
    nb_path = notebook_path(repo_root)
    out_path = output or default_output_path(repo_root)

    with open(nb_path, encoding="utf-8") as fh:
        nb = nbformat.read(fh, as_version=4)

    ep = ExecutePreprocessor(
        timeout=timeout,
        kernel_name="python3",
        allow_errors=True,
    )
    ep.preprocess(nb, {"metadata": {"path": str(repo_root)}})

    exporter = HTMLExporter()
    exporter.exclude_input = not show_input
    exporter.embed_images = True
    body, _ = exporter.from_notebook_node(nb)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Destination HTML file (default: backtest/notebooks/results.html)",
    )
    parser.add_argument(
        "--show-input",
        action="store_true",
        help="Include code cells in the rendered output",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        metavar="N",
        help="Per-cell execution timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    try:
        out = export(
            output=args.output,
            show_input=args.show_input,
            timeout=args.timeout,
        )
        print(f"Exported: {out}")
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
