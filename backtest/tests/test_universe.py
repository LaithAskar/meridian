"""Tests for backtest/universe.py"""

from backtest.universe import UNIVERSE_2016


class TestUniverse2016:
    def test_exactly_100_tickers(self):
        assert len(UNIVERSE_2016) == 100

    def test_all_uppercase(self):
        for ticker in UNIVERSE_2016:
            assert ticker == ticker.upper(), f"Ticker not uppercase: {ticker!r}"

    def test_no_duplicates(self):
        assert len(UNIVERSE_2016) == len(set(UNIVERSE_2016)), "Duplicate ticker(s) found"
