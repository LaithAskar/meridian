from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd
import numpy as np

from backend.utils.helpers import safe_float
from backend.services.technical import compute_rsi, compute_macd, compute_sma, compute_ema, compute_bollinger, compute_atr

logger = logging.getLogger(__name__)

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    logger.warning("XGBoost not available")

try:
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    features = pd.DataFrame(index=df.index)
    features["returns_1d"] = close.pct_change(1)
    features["returns_5d"] = close.pct_change(5)
    features["returns_10d"] = close.pct_change(10)
    features["returns_20d"] = close.pct_change(20)
    features["volatility_10d"] = close.pct_change().rolling(10).std()
    features["volatility_20d"] = close.pct_change().rolling(20).std()
    features["sma_10"] = compute_sma(close, 10) / close - 1
    features["sma_20"] = compute_sma(close, 20) / close - 1
    features["sma_50"] = compute_sma(close, 50) / close - 1
    features["ema_12"] = compute_ema(close, 12) / close - 1
    features["ema_26"] = compute_ema(close, 26) / close - 1
    features["rsi"] = compute_rsi(close, 14) / 100
    macd = compute_macd(close)
    features["macd"] = macd["histogram"] / close
    bb = compute_bollinger(close)
    bb_range = bb["upper"] - bb["lower"]
    features["bb_position"] = (close - bb["lower"]) / bb_range.replace(0, np.nan)
    features["atr"] = compute_atr(high, low, close) / close
    features["volume_sma"] = volume / volume.rolling(20).mean() - 1
    features["high_low_range"] = (high - low) / close
    features["gap"] = (df["Open"] - close.shift(1)) / close.shift(1)

    return features.replace([np.inf, -np.inf], np.nan).fillna(0)


def predict_xgboost(ticker: str, days: int = 30) -> Optional[dict[str, Any]]:
    if not XGBOOST_AVAILABLE or not SKLEARN_AVAILABLE:
        return None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        df = t.history(period="2y", interval="1d")
        if df is None or df.empty or len(df) < 100:
            return None

        features = _build_features(df)
        close = df["Close"]

        # Target: N-day forward return
        target_days = min(days, 30)
        target = close.shift(-target_days) / close - 1
        target = target.fillna(0)

        # Align and clean
        valid_idx = features.dropna().index.intersection(target.dropna().index)
        X = features.loc[valid_idx].values
        y = target.loc[valid_idx].values

        if len(X) < 60:
            return None

        # Scale
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Train on all but last portion
        split = max(int(len(X_scaled) * 0.8), len(X_scaled) - 60)
        X_train, X_test = X_scaled[:split], X_scaled[split:]
        y_train, y_test = y[:split], y[split:]

        model = XGBRegressor(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train)

        # Score on test
        test_score = model.score(X_test, y_test)

        # Predict from latest features
        last_features = features.iloc[-1:].values
        last_scaled = scaler.transform(last_features)
        predicted_return = float(model.predict(last_scaled)[0])

        current_price = safe_float(close.iloc[-1])
        predicted_price = current_price * (1 + predicted_return)
        change_pct = predicted_return * 100

        # Generate daily predictions by interpolation
        pred_prices = []
        for d in range(1, days + 1):
            frac = d / days
            day_price = current_price + (predicted_price - current_price) * frac
            noise = np.random.normal(0, current_price * 0.005)
            day_price += noise
            date = pd.Timestamp.now() + pd.Timedelta(days=d)
            pred_prices.append({
                "date": str(date.date()),
                "price": round(day_price, 2),
                "upper": round(day_price * 1.05, 2),
                "lower": round(day_price * 0.95, 2),
            })

        # Feature importance
        importances = model.feature_importances_
        feature_names = list(features.columns)
        importance_list = sorted(
            [{"feature": feature_names[i], "importance": round(float(importances[i]), 4)}
             for i in range(len(feature_names))],
            key=lambda x: x["importance"], reverse=True,
        )[:10]

        confidence = min(85, max(20, test_score * 100 + 40))

        return {
            "model": "xgboost",
            "currentPrice": round(current_price, 2),
            "predictedPrice": round(predicted_price, 2),
            "changePercent": round(change_pct, 2),
            "confidence": round(confidence, 1),
            "predictions": pred_prices,
            "direction": "up" if change_pct > 1 else "down" if change_pct < -1 else "sideways",
            "featureImportance": importance_list,
            "testScore": round(test_score, 4),
        }
    except Exception as e:
        logger.error(f"XGBoost prediction error for {ticker}: {e}")
        return None
