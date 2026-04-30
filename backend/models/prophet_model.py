from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd
import numpy as np

from backend.utils.helpers import safe_float

logger = logging.getLogger(__name__)

try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    logger.warning("Prophet not available, predictions will be limited")


def predict_prophet(ticker: str, days: int = 30) -> Optional[dict[str, Any]]:
    if not PROPHET_AVAILABLE:
        return None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        df = t.history(period="2y", interval="1d")
        if df is None or df.empty or len(df) < 60:
            return None

        df = df.reset_index()
        prophet_df = pd.DataFrame({
            "ds": df["Date"] if "Date" in df.columns else df.index,
            "y": df["Close"].values,
        })
        prophet_df["ds"] = pd.to_datetime(prophet_df["ds"]).dt.tz_localize(None)
        prophet_df = prophet_df.dropna()

        model = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
        )
        model.fit(prophet_df)

        future = model.make_future_dataframe(periods=days)
        forecast = model.predict(future)

        predictions = forecast.tail(days)
        current_price = safe_float(prophet_df["y"].iloc[-1])

        pred_prices = []
        for _, row in predictions.iterrows():
            pred_prices.append({
                "date": str(row["ds"].date()),
                "price": round(safe_float(row["yhat"]), 2),
                "upper": round(safe_float(row["yhat_upper"]), 2),
                "lower": round(safe_float(row["yhat_lower"]), 2),
            })

        final_price = safe_float(predictions["yhat"].iloc[-1])
        change_pct = ((final_price - current_price) / current_price * 100) if current_price > 0 else 0

        return {
            "model": "prophet",
            "currentPrice": round(current_price, 2),
            "predictedPrice": round(final_price, 2),
            "changePercent": round(change_pct, 2),
            "confidence": round(safe_float(1 - predictions["yhat_upper"].std() / (current_price + 1e-10)) * 100, 1),
            "predictions": pred_prices,
            "direction": "up" if change_pct > 1 else "down" if change_pct < -1 else "sideways",
        }
    except Exception as e:
        logger.error(f"Prophet prediction error for {ticker}: {e}")
        return None
