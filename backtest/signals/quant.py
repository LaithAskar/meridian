"""
Quant signal wrapper for the Meridian backtester.

Wraps the backend quant signal pipeline (momentum + mean-reversion +
regime-adjusted aggregation) for use in an offline event-loop backtest.

The live ``detect_regime`` function from
``backend.trading.quant.regime_detector`` is NOT used here because it calls
yfinance at runtime and is decorated with a TTL cache.  Instead, regime is
computed from SPY and VIX close series pre-loaded at construction time.  If
those series are not supplied, the regime defaults to "neutral" throughout.

Signal pipeline per bar
-----------------------
1. Accumulate OHLCV history into an internal buffer (no look-ahead bias).
2. Once ``min_history_bars`` bars have accumulated, compute:
   a. Cross-sectional + time-series momentum via ``momentum_signals``.
   b. RSI + Bollinger-Band + z-score mean-reversion via
      ``mean_reversion_signals``.
   c. Market regime (crisis / high_volatility / bull_trend / bear_trend /
      neutral) from SPY SMA50/SMA200 and VIX level, using only data up to
      and including the current timestamp.
3. Aggregate with regime-adjusted weights via ``aggregate_signals``.
   Factor signals are excluded throughout (DESIGN.md: no factor model).
4. Convert aggregated signals to Orders:
   - SELL: exit any held position whose aggregate direction is "sell".
   - BUY:  enter highest-conviction "buy" signals not already held,
     equal-weighted at ``equity / max_positions`` per slot, capped at
     available cash and ``max_positions`` concurrent holdings.

Regime weight table mirrors ``backend/trading/quant/regime_detector.py``;
the factor column is zeroed because no factor signals are generated.
``aggregate_signals`` normalises by total contributing weight, so passing
``factor=0.0`` with an empty factor-signal list is correct and lossless.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd

from backend.services.technical import compute_sma
from backend.trading.quant.mean_reversion import mean_reversion_signals
from backend.trading.quant.momentum import momentum_signals
from backend.trading.quant.signal_aggregator import aggregate_signals
from backtest.strategy import Order, Portfolio, Strategy

# Mirrors the weight table in backend/trading/quant/regime_detector.py.
# Factor weight is zero throughout (factor model excluded per DESIGN.md).
_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "crisis":          {"momentum": 0.10, "mean_reversion": 0.60, "factor": 0.0},
    "high_volatility": {"momentum": 0.20, "mean_reversion": 0.50, "factor": 0.0},
    "bull_trend":      {"momentum": 0.50, "mean_reversion": 0.20, "factor": 0.0},
    "bear_trend":      {"momentum": 0.15, "mean_reversion": 0.45, "factor": 0.0},
    "neutral":         {"momentum": 0.35, "mean_reversion": 0.30, "factor": 0.0},
}

_VIX_CRISIS_LEVEL = 30.0
_VIX_HIGH_VOL_LEVEL = 22.0


class QuantStrategy(Strategy):
    """
    Backtestable strategy driven by the Meridian quant signal pipeline.

    Parameters
    ----------
    max_positions    : Maximum concurrent long positions.  Equal-weight
                       sizing targets ``equity / max_positions`` per slot.
    min_history_bars : Minimum accumulated bars before any signal is emitted.
                       60 matches the hard minimum required by
                       ``momentum_signals`` (cross-sectional ranking
                       requires a full quintile, and 12m momentum needs
                       enough history to be meaningful).
    spy_close        : SPY daily close prices (DatetimeIndex pd.Series) used
                       for regime detection.  If None, regime is always
                       "neutral".
    vix_close        : VIX daily close prices (same shape) used for the
                       crisis / high_volatility regime thresholds.  If None,
                       VIX defaults to 20 (mid-range, avoids stress regimes).
    min_consensus    : Minimum directional vote fraction forwarded to
                       ``aggregate_signals``.  Default 0.55 means momentum
                       and mean-reversion must agree to trigger a trade.
    """

    def __init__(
        self,
        max_positions: int = 10,
        min_history_bars: int = 60,
        spy_close: pd.Series | None = None,
        vix_close: pd.Series | None = None,
        min_consensus: float = 0.55,
    ) -> None:
        super().__init__(max_positions=max_positions)
        self._min_history_bars = min_history_bars
        self._spy_close = spy_close
        self._vix_close = vix_close
        self._min_consensus = min_consensus
        # Capitalised keys match what backend signal functions expect (df["Close"], etc.)
        self._history: dict[str, list[dict[str, float]]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Strategy ABC implementation
    # ------------------------------------------------------------------

    def on_bar(
        self,
        ts: datetime,
        bars: dict[str, pd.Series],
        portfolio: Portfolio,
    ) -> list[Order]:
        """
        Called once per trading day by the Engine.

        Accumulates bar data, waits for ``min_history_bars``, then computes
        signals and returns a list of Orders to be filled at the next open.
        """
        # 1. Accumulate — store with capitalised keys for backend compat
        for sym, row in bars.items():
            self._history[sym].append({
                "Close":  float(row["close"]),
                "Open":   float(row["open"]),
                "High":   float(row["high"]),
                "Low":    float(row["low"]),
                "Volume": float(row["volume"]),
            })

        # 2. Warm-up gate
        max_bars = max((len(v) for v in self._history.values()), default=0)
        if max_bars < self._min_history_bars:
            return []

        # 3. Build universe_data — each symbol needs ≥ 30 bars (mean-rev min)
        universe_data: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(rows)
            for sym, rows in self._history.items()
            if len(rows) >= 30
        }
        if not universe_data:
            return []

        # 4. Compute momentum + mean-reversion signals
        mom_sigs = momentum_signals(universe_data)
        rev_sigs = mean_reversion_signals(universe_data)

        # 5. Aggregate with regime-adjusted weights (factor list is empty)
        regime_info = self._regime_at(pd.Timestamp(ts))
        agg = aggregate_signals(
            momentum_signals=mom_sigs,
            reversion_signals=rev_sigs,
            factor_signals=[],
            strategy_weights=regime_info["strategyWeights"],
            min_consensus=self._min_consensus,
        )

        # 6. Convert to Orders
        current_prices = {sym: float(row["close"]) for sym, row in bars.items()}
        equity_now = portfolio.equity(current_prices)
        target_per_slot = equity_now / self.max_positions if self.max_positions > 0 else 0.0

        orders: list[Order] = []
        # Track available cash separately to avoid issuing orders that
        # collectively exceed the portfolio's buying power.
        virtual_cash = portfolio.cash

        # Sells first: exit any held position with an aggregate sell signal.
        sell_targets = {s["ticker"] for s in agg if s["direction"] == "sell"}
        for sym, pos in list(portfolio.positions.items()):
            if sym in sell_targets:
                orders.append(Order(symbol=sym, side="sell", qty=pos.qty))
                virtual_cash += pos.qty * current_prices.get(sym, pos.avg_cost)

        # Buys: fill open slots with highest-conviction buy signals.
        n_sells = sum(1 for o in orders if o.side == "sell")
        open_slots = self.max_positions - (portfolio.num_positions - n_sells)

        buy_candidates = sorted(
            [s for s in agg if s["direction"] == "buy"],
            key=lambda s: s["ensembleScore"],
            reverse=True,
        )

        for sig in buy_candidates:
            if open_slots <= 0:
                break
            sym = sig["ticker"]
            if sym in portfolio.positions:
                continue  # already long; don't double-buy
            price = current_prices.get(sym, 0.0)
            if price <= 0.0:
                continue
            qty = math.floor(target_per_slot / price)
            if qty < 1:
                continue
            cost = qty * price
            if virtual_cash < cost:
                continue
            orders.append(Order(symbol=sym, side="buy", qty=float(qty)))
            virtual_cash -= cost
            open_slots -= 1

        return orders

    # ------------------------------------------------------------------
    # Regime detection (offline version of detect_regime)
    # ------------------------------------------------------------------

    def _regime_at(self, ts: pd.Timestamp) -> dict[str, Any]:
        """
        Classify the market regime at *ts* using SPY trend and VIX level.

        Replicates the logic of
        ``backend.trading.quant.regime_detector.detect_regime`` but reads
        from pre-loaded historical Series instead of making live network
        calls.  Only data up to and including *ts* is used (no look-ahead).
        """
        vix_level = 20.0  # default: mid-range, avoids the stress regimes
        if self._vix_close is not None:
            vix_hist = self._vix_close.loc[:ts]
            if not vix_hist.empty:
                vix_level = float(vix_hist.iloc[-1])

        if self._spy_close is None:
            return {"regime": "neutral", "strategyWeights": _REGIME_WEIGHTS["neutral"]}

        spy_hist = self._spy_close.loc[:ts]
        if spy_hist.empty:
            return {"regime": "neutral", "strategyWeights": _REGIME_WEIGHTS["neutral"]}

        spy_current = float(spy_hist.iloc[-1])
        spy_sma50 = float(compute_sma(spy_hist, 50).iloc[-1])
        # Fall back to SMA50 when fewer than 200 bars of SPY history exist
        spy_sma200 = (
            float(compute_sma(spy_hist, 200).iloc[-1])
            if len(spy_hist) >= 200
            else spy_sma50
        )

        if vix_level > _VIX_CRISIS_LEVEL:
            regime = "crisis"
        elif vix_level > _VIX_HIGH_VOL_LEVEL:
            regime = "high_volatility"
        elif spy_current > spy_sma50 > spy_sma200:
            regime = "bull_trend"
        elif spy_current < spy_sma50 < spy_sma200:
            regime = "bear_trend"
        else:
            regime = "neutral"

        return {"regime": regime, "strategyWeights": _REGIME_WEIGHTS[regime]}
