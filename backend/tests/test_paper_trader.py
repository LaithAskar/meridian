"""
Tests for backend.paper_trader.

The actual paper run is CPU-heavy (it re-runs the full backtest), so these
tests only verify the public interface, the strategy registry, the FNSPID
cap behavior, and the argparse plumbing — without invoking a real run.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import backend.paper_trader as pt


class TestPublicInterface:
    def test_runners_registered_for_all_three_strategies(self):
        assert set(pt._RUNNERS.keys()) == {"quant", "vader", "finbert"}
        for runner in pt._RUNNERS.values():
            assert callable(runner)

    def test_run_paper_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="unknown strategy"):
            pt.run_paper("bogus")

    def test_paper_start_is_canonical_backtest_start(self):
        assert pt.PAPER_START == date(2010, 1, 1)

    def test_fnspid_end_matches_dataset_cutoff(self):
        # FNSPID dataset stops 2023-12-31; sentiment paper runs must cap here.
        assert pt.FNSPID_END == date(2023, 12, 31)


class TestSentimentCapBehavior:
    def test_sentiment_runners_cap_end_at_fnspid(self, tmp_path, monkeypatch):
        # Stub the underlying backtest runner to record what end-date it sees.
        recorded: dict[str, date] = {}

        def fake_vader(*, start, end, initial_cash, output_dir):
            recorded["vader_end"] = end
            return {
                "run_date": "2026-05-17",
                "parameters": {"start": start.isoformat(), "end": end.isoformat()},
                "full_window": {"sharpe": 0.0},
            }

        def fake_finbert(*, start, end, initial_cash, output_dir):
            recorded["finbert_end"] = end
            return {
                "run_date": "2026-05-17",
                "parameters": {"start": start.isoformat(), "end": end.isoformat()},
                "full_window": {"sharpe": 0.0},
            }

        import backtest.run_vader as rv
        import backtest.run_finbert as rf
        monkeypatch.setattr(rv, "run_vader_backtest", fake_vader)
        monkeypatch.setattr(rf, "run_finbert_backtest", fake_finbert)

        # Request end well past FNSPID cutoff
        future = date(2026, 5, 17)
        m_v = pt.run_paper("vader", end=future, paper_dir=tmp_path)
        m_f = pt.run_paper("finbert", end=future, paper_dir=tmp_path)

        # Both must have been called with end = FNSPID_END, not the future
        assert recorded["vader_end"] == pt.FNSPID_END
        assert recorded["finbert_end"] == pt.FNSPID_END

        # Both metrics must carry the data_limit_note so the dashboard can warn
        assert "data_limit_note" in m_v
        assert "data_limit_note" in m_f
        assert m_v["mode"] == "paper"
        assert m_f["mode"] == "paper"
        assert m_v["paper_end"] == pt.FNSPID_END.isoformat()

    def test_sentiment_runner_within_fnspid_window_no_warning(self, tmp_path, monkeypatch):
        # When the requested end is within the FNSPID window, no warning fires.
        recorded: dict[str, date] = {}

        def fake_vader(*, start, end, initial_cash, output_dir):
            recorded["vader_end"] = end
            return {
                "run_date": "2026-05-17",
                "parameters": {"start": start.isoformat(), "end": end.isoformat()},
                "full_window": {"sharpe": 0.0},
            }

        import backtest.run_vader as rv
        monkeypatch.setattr(rv, "run_vader_backtest", fake_vader)

        within = date(2023, 6, 30)
        m = pt.run_paper("vader", end=within, paper_dir=tmp_path)

        assert recorded["vader_end"] == within
        assert "data_limit_note" not in m


class TestQuantNoCap:
    def test_quant_runner_does_not_cap_end_date(self, tmp_path, monkeypatch):
        recorded: dict[str, date] = {}

        def fake_quant(*, start, end, initial_cash, output_dir):
            recorded["quant_end"] = end
            return {
                "run_date": "2026-05-17",
                "parameters": {"start": start.isoformat(), "end": end.isoformat()},
                "full_window": {"sharpe": 0.0},
            }

        import backtest.run_quant as rq
        monkeypatch.setattr(rq, "run_quant_backtest", fake_quant)

        future = date(2026, 5, 17)
        m = pt.run_paper("quant", end=future, paper_dir=tmp_path)
        assert recorded["quant_end"] == future
        assert "data_limit_note" not in m
        assert m["mode"] == "paper"
        assert m["paper_end"] == future.isoformat()
