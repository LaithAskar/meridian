from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize

from backend.utils.helpers import safe_float, safe_div

logger = logging.getLogger(__name__)


def optimize_portfolio(
    tickers: list[str],
    investment_amount: float = 10000,
    risk_tolerance: str = "moderate",
    period: str = "1y",
) -> dict[str, Any]:
    try:
        tickers = [t.upper().strip() for t in tickers if t.strip()]
        if len(tickers) < 2:
            return {"error": "Need at least 2 tickers for portfolio optimization"}

        # Download data
        data = yf.download(tickers, period=period, interval="1d", progress=False)
        if data is None or data.empty:
            return {"error": "Could not fetch price data"}

        close = data["Close"] if "Close" in data.columns else data.get("Adj Close")
        if close is None or close.empty:
            return {"error": "No price data available"}

        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])

        close = close.dropna(how="all").ffill().dropna()
        valid_tickers = [t for t in tickers if t in close.columns and close[t].notna().sum() > 20]
        if len(valid_tickers) < 2:
            return {"error": "Not enough valid price data"}

        close = close[valid_tickers]
        returns = close.pct_change().dropna()

        mean_returns = returns.mean() * 252
        cov_matrix = returns.cov() * 252
        n = len(valid_tickers)

        risk_map = {"conservative": 0.3, "moderate": 0.5, "aggressive": 0.8}
        risk_factor = risk_map.get(risk_tolerance, 0.5)

        def neg_sharpe(weights):
            port_return = np.dot(weights, mean_returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            return -(port_return - 0.04) / (port_vol + 1e-10)

        def min_vol(weights):
            return np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = tuple((0.02, 0.5) for _ in range(n))
        init = np.array([1 / n] * n)

        # Max Sharpe
        try:
            sharpe_result = minimize(neg_sharpe, init, method="SLSQP", bounds=bounds, constraints=constraints)
            sharpe_weights = sharpe_result.x if sharpe_result.success else init
        except Exception:
            sharpe_weights = init

        # Min Volatility
        try:
            vol_result = minimize(min_vol, init, method="SLSQP", bounds=bounds, constraints=constraints)
            vol_weights = vol_result.x if vol_result.success else init
        except Exception:
            vol_weights = init

        # Blend based on risk tolerance
        weights = risk_factor * sharpe_weights + (1 - risk_factor) * vol_weights
        weights = weights / weights.sum()

        port_return = float(np.dot(weights, mean_returns))
        port_vol = float(np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights))))
        sharpe = safe_div(port_return - 0.04, port_vol)

        # Kelly criterion
        kelly_fractions = []
        for i, t in enumerate(valid_tickers):
            mu = float(mean_returns.iloc[i]) if hasattr(mean_returns, 'iloc') else float(mean_returns[i])
            var = float(cov_matrix.iloc[i, i]) if hasattr(cov_matrix, 'iloc') else float(cov_matrix[i][i])
            kelly = safe_div(mu - 0.04, var) if var > 0 else 0
            kelly_fractions.append(max(0, min(0.5, kelly * 0.5)))  # Half-Kelly

        # Build positions
        positions = []
        for i, t in enumerate(valid_tickers):
            w = float(weights[i])
            alloc = round(w * investment_amount, 2)
            current_price = safe_float(close[t].iloc[-1])
            shares = int(alloc / current_price) if current_price > 0 else 0
            ann_return = float(mean_returns.iloc[i]) if hasattr(mean_returns, 'iloc') else float(mean_returns[i])
            ann_vol = float(np.sqrt(cov_matrix.iloc[i, i] if hasattr(cov_matrix, 'iloc') else cov_matrix[i][i]))

            positions.append({
                "ticker": t,
                "weight": round(w * 100, 2),
                "allocation": alloc,
                "shares": shares,
                "currentPrice": round(current_price, 2),
                "expectedReturn": round(ann_return * 100, 2),
                "volatility": round(ann_vol * 100, 2),
                "kellyFraction": round(kelly_fractions[i] * 100, 2),
            })

        positions.sort(key=lambda x: x["weight"], reverse=True)

        # Correlation matrix
        corr = returns.corr()
        corr_data = {}
        for t1 in valid_tickers:
            corr_data[t1] = {}
            for t2 in valid_tickers:
                corr_data[t1][t2] = round(float(corr.loc[t1, t2]), 3)

        return {
            "summary": {
                "expectedReturn": round(port_return * 100, 2),
                "volatility": round(port_vol * 100, 2),
                "sharpeRatio": round(sharpe, 3),
                "investmentAmount": investment_amount,
                "riskTolerance": risk_tolerance,
                "numAssets": n,
            },
            "positions": positions,
            "correlation": corr_data,
            "riskWarnings": _get_risk_warnings(positions, port_vol, sharpe, corr_data),
        }
    except Exception as e:
        logger.error(f"Portfolio optimization error: {e}")
        return {"error": str(e)}


def _get_risk_warnings(positions, vol, sharpe, corr) -> list[dict]:
    warnings = []
    max_weight = max(p["weight"] for p in positions) if positions else 0
    if max_weight > 35:
        warnings.append({"level": "warning", "message": f"Concentration risk: largest position is {max_weight:.1f}%"})
    if vol > 0.3:
        warnings.append({"level": "warning", "message": f"High portfolio volatility: {vol*100:.1f}%"})
    if sharpe < 0.5:
        warnings.append({"level": "info", "message": f"Low risk-adjusted return (Sharpe: {sharpe:.2f})"})

    # Check for high correlations
    tickers = list(corr.keys())
    for i, t1 in enumerate(tickers):
        for t2 in tickers[i+1:]:
            if abs(corr[t1][t2]) > 0.8:
                warnings.append({"level": "info", "message": f"High correlation between {t1} and {t2}: {corr[t1][t2]:.2f}"})
    return warnings
